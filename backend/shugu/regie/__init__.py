"""Régie — namespace canonique du projet pour les composants d'orchestration.

Ce package regroupe deux sous-modules complémentaires :

- ``regie.voice_intent`` — classification d'intent voix VTuber (CHAT / WEB_SEARCH /
  EMOTION / EMOTE), parser tool calls Gemma, providers web search Tavily/Brave.
  Utilisé par le pipeline LiveKit voix (``voice/livekit_agent.py``). Relocalisé
  depuis ``backend/shugu/voice/regie/`` au sprint R.0.5.

- ``regie.control_room`` — plateau technique : pilote scènes / timers / sons /
  events stream / modération sur ordre admin. À livrer aux sprints R.1 → R.12
  (voir ``docs/REGIE-ARCHITECTURE.md``).

Les deux sous-modules sont distincts (rôles, sources, latence cible) mais
partagent un même namespace pour éviter la dispersion de code "régie-like".

Conforme à la règle cardinale ``docs/PHASE1-FOUNDATION.md`` :
les *senses*, *régie*, *memory* sont des **services** Python (pas des agents LLM).
"""
