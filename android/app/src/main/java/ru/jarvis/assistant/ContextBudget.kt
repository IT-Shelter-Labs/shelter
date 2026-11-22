package ru.jarvis.assistant

object ContextBudget {
    // Keep complete pairs. The database retains the full conversation; only
    // the request window is bounded. Never cut half a sentence or invent a summary.
    fun recent(lines: List<ChatLine>, chars: Int): List<ChatLine> {
        val pairs = lines.chunked(2).filter { it.size == 2 && it[0].role == "user" && it[1].role == "assistant" }
        val selected = mutableListOf<List<ChatLine>>()
        var used = 0
        for (pair in pairs.asReversed()) {
            val cost = pair.sumOf { it.text.length }
            if (used + cost > chars) break
            used += cost; selected.add(pair)
        }
        return selected.asReversed().flatten()
    }
}
