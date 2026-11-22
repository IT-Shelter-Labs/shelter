import { open as nativeOpen, save as nativeSave, type OpenDialogOptions, type SaveDialogOptions } from '@tauri-apps/plugin-dialog';
import { translate } from './i18n';
import { language } from './language';
function labels<T extends OpenDialogOptions|SaveDialogOptions>(options:T):T {
  return {...options,title:options.title?translate(options.title,language()):undefined,
    filters:options.filters?.map(filter=>({...filter,name:translate(filter.name,language())}))};
}
export const open = (options:OpenDialogOptions={}) => nativeOpen(labels(options));
export const save = (options:SaveDialogOptions={}) => nativeSave(labels(options));
