"""Tests unit régie — tool_call_parser + intent_classifier."""
from __future__ import annotations

from shugu.voice.regie.intent_classifier import Intent, classify
from shugu.voice.regie.tool_call_parser import (
    has_tool_calls,
    parse_gemma_tool_calls,
)


class TestGemmaToolCallParser:
    def test_single_tool_call(self):
        text = '<|tool_call>call:web_search{query:<|"|>météo Paris<|"|>}<tool_call|>'
        calls = parse_gemma_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["name"] == "web_search"
        assert calls[0]["arguments"] == {"query": "météo Paris"}

    def test_chained_tool_calls(self):
        text = (
            '<|tool_call>call:set_avatar_emotion{emotion:<|"|>happy<|"|>}<tool_call|>'
            '<|tool_call>call:play_emote{emote:<|"|>wave<|"|>}<tool_call|>'
        )
        calls = parse_gemma_tool_calls(text)
        assert len(calls) == 2
        assert calls[0] == {"name": "set_avatar_emotion", "arguments": {"emotion": "happy"}}
        assert calls[1] == {"name": "play_emote", "arguments": {"emote": "wave"}}

    def test_no_tool_call(self):
        assert parse_gemma_tool_calls("Salut !") == []
        assert has_tool_calls("Salut !") is False

    def test_multi_arg(self):
        text = '<|tool_call>call:my_tool{a:<|"|>1<|"|>,b:<|"|>2<|"|>}<tool_call|>'
        calls = parse_gemma_tool_calls(text)
        assert calls[0]["arguments"] == {"a": "1", "b": "2"}


class TestIntentClassifier:
    def test_web_search_meteo(self):
        assert classify("Quel temps il fait à Paris ?").intent == Intent.WEB_SEARCH

    def test_web_search_pib(self):
        assert classify("Tu connais le PIB de la France en 2026 ?").intent == Intent.WEB_SEARCH

    def test_emotion_loto(self):
        assert classify("Wow, j'ai gagné le loto !").intent == Intent.EMOTION

    def test_emote_salut(self):
        assert classify("Salut Shugu !").intent == Intent.EMOTE

    def test_chat_default(self):
        assert classify("Tu fais quoi ce soir ?").intent == Intent.CHAT

    def test_priority_web_over_emote(self):
        # "Salut" + "météo" → web_search (priority)
        assert classify("Salut, c'est quoi la météo ?").intent == Intent.WEB_SEARCH
