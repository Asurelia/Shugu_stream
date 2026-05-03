"""Régie pré-LLM voice — pre-routing déterministe + post-process custom parsers.

Comble les défauts du tool calling LLM-driven (T4 web_search non déclenché auto)
en ajoutant une couche Python en amont du LLM qui :
1. Classifie l'intent de la query (rules + small LLM gate optionnel)
2. Fetch les tools déterministes en parallèle si pertinent
3. Augmente le system prompt avec le contexte récupéré
4. Post-process l'output (custom parser tool_call Gemma + sentiment + safety)

Modules :
- intent_classifier  : intent → chat / web_search / emotion / emote
- tool_call_parser   : Gemma format `<|tool_call>call:N{...}<tool_call|>` → dict
- web_search_tool    : Tavily/Brave API (Sprint C)
- avatar_control     : sentiment + keyword → emotion/emote events
- prompt_builder     : system prompt augmenté
- safety_filter      : réutilise injection_detector

See docs/specs/2026-05-03-realtime-voice-shugu.md §5.bis pour le design complet.
"""
