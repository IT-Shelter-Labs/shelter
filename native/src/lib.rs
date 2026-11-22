//! Small C ABI: no Python runtime, GUI, model weights or background process.
//! Callers own input/output buffers and must pass valid, nonoverlapping memory.
use std::collections::HashMap;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::{Mutex, OnceLock};
mod media;

#[no_mangle]
pub extern "C" fn jarvis_native_version() -> u32 { 1 }

fn gcd(mut a: usize, mut b: usize) -> usize { while b != 0 { (a, b) = (b, a % b); } a }
fn i0(x: f64) -> f64 {
    let mut term = 1.; let mut sum = 1.;
    for k in 1..60 { term *= x * x / (4. * (k * k) as f64); sum += term; if term < sum * 1e-16 { break; } }
    sum
}
type FilterCache = HashMap<(usize, usize), Vec<f32>>;
static FILTERS: OnceLock<Mutex<FilterCache>> = OnceLock::new();

/// Same zero-padded, Kaiser(beta=5), 20*max(up,down)+1 FIR as resample_poly.
fn coefficients(up: usize, down: usize) -> Vec<f32> {
    let max = up.max(down); let half = 10 * max; let denom = i0(5.);
    let mut h: Vec<f64> = (0..=2 * half).map(|n| {
        let x = n as f64 - half as f64; let cutoff = 1. / max as f64;
        let a = std::f64::consts::PI * cutoff * x;
        let sinc = if x == 0. { cutoff } else { a.sin() / (std::f64::consts::PI * x) };
        sinc * i0(5. * (1. - (x / half as f64).powi(2)).max(0.).sqrt()) / denom
    }).collect();
    let sum: f64 = h.iter().sum();
    // Match float32 FIR coefficient rounding before multiplication by up.
    h.drain(..).map(|v| (v / sum) as f32 * up as f32).collect()
}
fn resample(x: &[f32], out: &mut [f32], up: usize, down: usize) {
    if up == down { out.copy_from_slice(x); return; }
    let mut cache = FILTERS.get_or_init(Default::default).lock().unwrap_or_else(|e| e.into_inner());
    if cache.len() >= 16 && !cache.contains_key(&(up,down)) { cache.clear(); }
    let h = cache.entry((up,down)).or_insert_with(|| coefficients(up,down));
    let half = 10 * up.max(down);
    for (j, y) in out.iter_mut().enumerate() {
        let center = j * down + half;
        let begin = center.saturating_sub(h.len() - 1).div_ceil(up);
        let end = (center / up + 1).min(x.len());
        let mut sum = 0f32;
        for n in begin..end { sum += x[n] * h[center - n * up]; }
        *y = sum;
    }
}

/// Returns output length; -1 invalid dimensions, -2 panic. Maximum ratio 4096.
#[no_mangle]
pub unsafe extern "C" fn jarvis_resample(input: *const f32, len: usize, output: *mut f32, capacity: usize, up: usize, down: usize) -> isize {
    if input.is_null() || output.is_null() || up == 0 || down == 0 || len > 100_000_000 { return -1; }
    let g = gcd(up,down); let (up,down) = (up/g,down/g);
    if up.max(down) > 4096 { return -1; }
    let Some(total) = len.checked_mul(up) else { return -1; };
    let count = total.div_ceil(down);
    if capacity < count { return -1; }
    catch_unwind(AssertUnwindSafe(|| {
        resample(std::slice::from_raw_parts(input,len), std::slice::from_raw_parts_mut(output,count),up,down);
        count as isize
    })).unwrap_or(-2)
}

struct Ring { data: Vec<f32>, cursor: usize }
impl Ring {
    fn write(&mut self, x: &[f32]) {
        for &v in x { self.data[self.cursor] = v; self.cursor = (self.cursor + 1) % self.data.len(); }
    }
    fn read(&self, out: &mut [f32]) {
        let start = (self.cursor + self.data.len() - out.len()) % self.data.len();
        for (i,v) in out.iter_mut().enumerate() { *v = self.data[(start+i) % self.data.len()]; }
    }
}
#[no_mangle]
pub extern "C" fn jarvis_ring_new(capacity: usize) -> *mut std::ffi::c_void {
    if capacity == 0 || capacity > 10_000_000 { return std::ptr::null_mut(); }
    Box::into_raw(Box::new(Mutex::new(Ring{data:vec![0.;capacity],cursor:0}))).cast()
}
#[no_mangle]
pub unsafe extern "C" fn jarvis_ring_free(ring: *mut std::ffi::c_void) {
    if !ring.is_null() { drop(Box::from_raw(ring.cast::<Mutex<Ring>>())); }
}
#[no_mangle]
pub unsafe extern "C" fn jarvis_ring_write(ring: *mut std::ffi::c_void, input: *const f32, len: usize) -> i32 {
    if ring.is_null() || input.is_null() || len > 10_000_000 { return -1; }
    let Ok(mut ring) = (*ring.cast::<Mutex<Ring>>()).lock() else { return -2; };
    ring.write(std::slice::from_raw_parts(input,len)); 0
}
#[no_mangle]
pub unsafe extern "C" fn jarvis_ring_read(ring: *mut std::ffi::c_void, output: *mut f32, len: usize) -> i32 {
    if ring.is_null() || output.is_null() { return -1; }
    let Ok(ring) = (*ring.cast::<Mutex<Ring>>()).lock() else { return -2; };
    if len > ring.data.len() { return -1; }
    ring.read(std::slice::from_raw_parts_mut(output,len)); 0
}

#[no_mangle]
pub unsafe extern "C" fn jarvis_media_snapshot(output: *mut u8, capacity: usize) -> isize {
    if output.is_null() { return -1; }
    catch_unwind(AssertUnwindSafe(|| {
        let Ok(value) = media::snapshot() else { return -1; };
        let bytes = value.to_string().into_bytes();
        if bytes.len() > capacity { return -1; }
        std::ptr::copy_nonoverlapping(bytes.as_ptr(),output,bytes.len()); bytes.len() as isize
    })).unwrap_or(-2)
}
#[no_mangle]
pub unsafe extern "C" fn jarvis_media_control(action: u32, source: *const u8, len: usize) -> i32 {
    if source.is_null() || len > 4096 { return -1; }
    let Ok(source) = std::str::from_utf8(std::slice::from_raw_parts(source,len)) else { return -1; };
    catch_unwind(|| media::control(action,source).map(i32::from).unwrap_or(-1)).unwrap_or(-2)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn ring_keeps_latest_samples_after_multiple_wraps() {
        let mut ring = Ring{data:vec![0.;4],cursor:0};
        ring.write(&[1.,2.,3.,4.,5.,6.,7.,8.,9.]); let mut out = [0.;4]; ring.read(&mut out);
        assert_eq!(out,[6.,7.,8.,9.]);
    }
    #[test] fn resampler_preserves_dc_and_length() {
        let x = vec![1.;3200]; let mut out = vec![0.;1600]; resample(&x,&mut out,1,2);
        assert!(out[30..1570].iter().all(|v| (*v-1.).abs()<1e-5));
    }
    #[test] fn invalid_ffi_dimensions_are_rejected() {
        assert_eq!(unsafe{jarvis_resample(std::ptr::null(),1,std::ptr::null_mut(),0,1,0)},-1);
        assert!(jarvis_ring_new(0).is_null());
    }
}
