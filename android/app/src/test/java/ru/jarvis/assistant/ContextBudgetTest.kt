package ru.jarvis.assistant
import org.junit.Assert.*
import org.junit.Test

class ContextBudgetTest {
    @Test fun retainsWholeRecentTurns() {
        val history = listOf(ChatLine("user", "old"), ChatLine("assistant", "answer"), ChatLine("user", "new"), ChatLine("assistant", "yes"))
        assertEquals(history.takeLast(2), ContextBudget.recent(history, 6))
        assertTrue(ContextBudget.recent(history, 5).isEmpty())
        assertEquals(4, history.size)
    }
    @Test fun rejectsOrphanedAssistantMessage() {
        assertTrue(ContextBudget.recent(listOf(ChatLine("assistant", "orphan")), 100).isEmpty())
    }
}
