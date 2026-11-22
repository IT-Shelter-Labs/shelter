package ru.jarvis.assistant
import org.junit.Assert.*
import org.junit.Test

class EndpointsTest {
    @Test fun changingServerOriginRequiresNewCredentials() {
        assertTrue(Endpoints.sameOrigin("https://example.com/v1", "https://EXAMPLE.com:443/v2"))
        assertFalse(Endpoints.sameOrigin("https://example.com/v1", "https://other.example.com/v1"))
        assertFalse(Endpoints.sameOrigin("http://localhost:8080/v1", "http://localhost:8081/v1"))
    }

    @Test fun localHttpNeedsExplicitOptIn() {
        assertThrows(IllegalArgumentException::class.java) { Endpoints.checked("http://192.168.1.5:8765", false) }
        assertEquals("http://192.168.1.5:8765", Endpoints.checked("http://192.168.1.5:8765/", true))
    }
    @Test fun keysAndPublicPlainHttpAreRejected() {
        listOf("http://example.com", "http://192.168.1.2.evil.test", "https://user:password@example.com", "https://example.com?token=abc").forEach {
            assertThrows(IllegalArgumentException::class.java) { Endpoints.checked(it, true) }
        }
        assertEquals("https://example.com/v1", Endpoints.checked("https://example.com/v1", false))
    }
}
