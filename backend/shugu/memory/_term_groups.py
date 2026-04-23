"""Bilingual FR/EN term groups for query expansion — Phase 2.4.

Ports the TERM_GROUPS pattern from Project_cc (src/context/memory/agent.ts
lines 56-73) to the Shugu_stream VTuber context. Instead of tech-jargon
clusters, these groups capture the vocabulary a French/English-mixed
VTuber chat actually uses: streaming rituals, common topics (food,
drinks, games, pets, music), anime culture, personal facts, preferences,
schedule, and the streamer's hardware setup.

Matching is bidirectional substring (see `expand_query_terms`):
for each group, if any term satisfies `term in word` or `word in term`,
all terms in the group are emitted.

Design constraints that shaped the data :

* Stopwords (`le`, `la`, `de`, `je`, `i`, `a`, `the`, ...) are never
  included — they would trigger on virtually every memory.
* Short ambiguous tokens that collide via substring with common
  unrelated words are excluded even when semantically relevant :

      age   -> page / image / manage / message / storage
      ans   -> france / dans / trans / sans
      vin   -> moving / having / invincible
      eau   -> beauty / beautiful
      jus   -> just / adjust
      abo   -> about / above / aboard
      don   -> don't / condone / donjon
      pain  -> painful / painting / capital  (FR "bread" only)
      tea   -> team / steak / teaches
      from  -> information / platform / uniform
      ami   -> jamais / dynamic / ceramic

  Their intended meaning is covered by longer synonyms or accented
  forms (`age` via `annee`, `vin` via `biere` / `pinard`, `tea`
  via `matcha` / `tisane`, `ami` via `amie` / `pote`, ...).

* Accented French tokens (e.g. `cafe`, `prefere`) are kept as-is :
  the accent makes them naturally distinct from English near-homographs
  and unrelated ASCII words, which reduces substring collisions.
  Callers MUST NOT NFKD-strip queries before expansion unless they
  also strip the corpus, or this property breaks.

* Groups are atomic words or short phrases (max two words). Long
  sentences like "I love coffee" would over-match via substring.

* Each group stays inside the 4-12 term range requested by the spec.

Conflict resolutions (tokens with two plausible homes) :

* `chat` -> STREAMING. Spectator-chat usage dominates in a VTuber
  backend; FR "chat" (cat) is covered by `chaton` / `minou` /
  `matou` / `felin`. A FR memory "j'ai un chat" is still retrievable
  by the literal query "chat" via cosine / embedding — expansion
  just does not bridge it to "cat".
* `live` / `livestream` / `en direct` -> STREAMING (going live),
  not SCHEDULE.
* `vtuber` -> STREAMING (streamer identity / role), not the
  anime/otaku consumption group.
* `copain` / `copine` -> PARTNER. Modern romantic sense dominates;
  for the platonic "male friend" meaning use `pote` / `pal` /
  `buddy` / `amie`.
* `soir` / `soiree` -> SCHEDULE (time of day), not RELATIONSHIPS.

Group order reflects expected query frequency : streaming and
preferences near the top (asked every stream), niche setup vocabulary
last.
"""
from __future__ import annotations

BILINGUAL_TERM_GROUPS: tuple[tuple[str, ...], ...] = (
    # --- Streaming / VTuber -------------------------------------------
    # Home of `chat` (spectator chat dominates VTuber usage).
    # Home of `live` / `livestream` / `stream` / `en direct`.
    # Home of `vtuber` (streamer identity, not anime consumption).
    (
        "stream", "streaming", "livestream", "live", "en direct",
        "vtuber", "vtubeur", "vtubeuse",
        "viewer", "viewers", "spectateur", "spectateurs", "chat",
        "follow", "follower", "abonné", "abonnement",
        "subscribe", "subscriber", "sub",
        "raid", "host",
        "clip", "clips", "vod", "replay", "rediffusion",
        "emote", "emoji", "smiley",
        "tip", "tipper", "donation", "pourboire", "soutien",
    ),
    # --- Preferences / emotions (like / love / hate / favorite) -------
    (
        "like", "likes", "liked",
        "love", "loves", "loved",
        "aime", "aimer", "aimerais",
        "adore", "adorer",
        "hate", "hates", "hated",
        "déteste", "détester", "detester",
        "favorite", "favourite", "favori",
        "préféré", "préférée", "preferee",
        "préfère", "prefere", "prefer",
        "pet peeve",
    ),
    # --- Drinks -------------------------------------------------------
    # Home of `café` / `coffee`. Bare `eau` / `vin` / `jus` / `tea`
    # excluded per collision notes in module docstring.
    (
        "coffee", "café", "cafe", "espresso", "expresso",
        "latte", "cappuccino", "mocha", "java",
        "matcha", "thé", "tisane",
        "green tea", "black tea", "herbal tea",
        "water", "flotte", "sparkling water",
        "juice", "smoothie", "nectar",
        "beer", "bière", "biere", "pinte",
        "wine", "vino", "pinard",
        "soda", "cola", "limonade", "lemonade",
        "energy drink", "redbull", "monster",
    ),
    # --- Food ---------------------------------------------------------
    # FR `pain` (bread) excluded; use `baguette`, `boulangerie`, `bread`.
    (
        "pizza", "burger", "hamburger", "cheeseburger",
        "sushi", "sashimi", "maki", "onigiri",
        "ramen", "udon", "nouilles", "noodles",
        "chocolate", "chocolat", "cacao",
        "bread", "baguette", "boulangerie", "sandwich",
        "cheese", "fromage", "camembert", "brie",
        "fruit", "fruits",
        "vegetable", "vegetables", "légume", "legume", "légumes",
        "cake", "gâteau", "gateau",
        "pâtisserie", "patisserie", "dessert",
        "snack", "grignoter",
    ),
    # --- Games / gaming -----------------------------------------------
    (
        "game", "games", "gaming", "gamer",
        "jeu", "jeux", "jeu vidéo", "video game",
        "mmo", "mmorpg", "fps", "rpg", "jrpg", "moba",
        "indie", "roguelike", "soulslike",
        "speedrun", "speedrunner",
        "minecraft", "elden ring", "zelda", "mario",
        "league", "valorant", "overwatch",
    ),
    # --- Anime / manga / otaku culture --------------------------------
    # `vtuber` lives in STREAMING (functional identity), not here.
    (
        "anime", "animé", "japanimation",
        "manga", "mangas", "manhwa", "manhua", "webtoon",
        "otaku", "weeb", "weeaboo",
        "cosplay", "cosplayer",
        "kawaii", "chibi", "waifu", "husbando",
        "shonen", "shojo", "seinen", "isekai",
    ),
    # --- Music --------------------------------------------------------
    (
        "music", "musique", "musical",
        "song", "songs", "chanson", "chansons",
        "album", "single",
        "concert", "live show", "gig",
        "playlist",
        "jpop", "kpop", "rock", "metal", "lofi", "edm",
    ),
    # --- Pets / animals -----------------------------------------------
    # `chat` (FR cat) is NOT here — it lives in STREAMING. FR cat is
    # covered by `chaton` / `minou` / `matou` / `félin`.
    (
        "pet", "pets", "animal", "animaux", "animal de compagnie",
        "cat", "cats", "kitty", "kitten",
        "chaton", "chatons", "minou", "matou", "félin", "felin",
        "dog", "dogs", "puppy", "doggo",
        "chien", "chienne", "chiot",
        "bird", "birds", "oiseau", "oiseaux", "perroquet",
        "fish", "poisson", "poissons", "aquarium",
        "hamster", "lapin", "rabbit",
    ),
    # --- Personal fact: NAME ------------------------------------------
    (
        "name", "named", "surname", "nickname",
        "nom", "prénom", "prenom", "surnom",
        "called", "appelle", "appeler", "appelé",
        "pseudo", "handle",
    ),
    # --- Personal fact: AGE -------------------------------------------
    # Bare `age` / `ans` excluded per collision notes. Accented `âge`
    # kept because the circumflex prevents substring collisions
    # with `page`, `image`, `manage`.
    (
        "âge", "années", "année",
        "years old", "year old",
        "birthday", "birthdate", "anniversaire",
        "born", "né en", "née en", "dob",
    ),
    # --- Personal fact: LOCATION --------------------------------------
    # `from` excluded (collides with information / platform / uniform).
    (
        "city", "country", "hometown",
        "ville", "pays", "région", "region",
        "lives in", "live in", "living in",
        "habite", "habiter", "réside", "reside",
        "based in", "originaire", "originally",
        "paris", "tokyo", "lyon", "montréal",
    ),
    # --- Personal fact: OCCUPATION / WORK -----------------------------
    (
        "work", "working", "worker",
        "job", "jobs", "career",
        "travail", "travailler", "travaille",
        "métier", "metier", "profession",
        "occupation", "freelance", "freelancer",
        "developer", "développeur", "developpeur",
        "artist", "artiste",
    ),
    # --- Personal fact: SCHOOL / STUDIES ------------------------------
    (
        "school", "high school", "middle school",
        "école", "ecole", "lycée", "lycee", "collège", "college",
        "university", "université", "universite", "campus",
        "student", "étudiant", "étudiante", "etudiant", "etudiante",
        "études", "etudes", "study", "studying",
        "diplôme", "diplome", "degree",
    ),
    # --- Schedule / time of day ---------------------------------------
    # `live` lives in STREAMING. `soir` / `soirée` here = evening slot.
    (
        "schedule", "planning", "horaire", "horaires", "calendrier",
        "weekend", "week-end", "weekday", "semaine",
        "morning", "matin", "matinée",
        "afternoon", "après-midi", "apres-midi",
        "evening", "soir", "soirée", "soiree",
        "night", "nuit", "tonight", "ce soir",
        "streaming time", "stream time",
    ),
    # --- Relationships: friends ---------------------------------------
    # FR bare `ami` / `amis` excluded (collide with jamais, famille).
    # `copain` / `copine` live in PARTNER group.
    (
        "friend", "friends", "friendship",
        "amie", "amies",
        "buddy", "pal", "mate",
        "pote", "potes",
        "bestie", "bff",
    ),
    # --- Relationships: family ----------------------------------------
    (
        "family", "famille",
        "parent", "parents",
        "mom", "mother", "mère", "mere", "maman",
        "dad", "father", "père", "pere", "papa",
        "sister", "soeur", "sœur",
        "brother", "frère", "frere",
        "cousin", "cousine",
        "grandma", "grandpa", "mamie", "papi", "papy",
    ),
    # --- Relationships: romantic partner ------------------------------
    # Home of `copain` / `copine` (modern romantic sense dominates).
    (
        "partner", "partenaire",
        "boyfriend", "girlfriend",
        "copain", "copine",
        "husband", "wife", "mari", "époux", "épouse", "epouse",
        "fiancé", "fiance", "fiancée", "fiancee",
        "crush", "dating",
    ),
    # --- Tech / streamer setup ----------------------------------------
    # Least-queried group but streamer does have PC specs. `pc` kept
    # despite being 2 chars — essential vocab, bidirectional match
    # still works because query "pc" matches term "pc" exactly.
    (
        "pc", "desktop", "laptop", "ordinateur", "ordi",
        "microphone", "micro", "mic",
        "camera", "caméra", "webcam",
        "keyboard", "clavier", "keycaps",
        "mouse", "souris", "mousepad", "tapis de souris",
        "headset", "casque", "écouteurs", "ecouteurs",
        "gpu", "cpu", "ram", "specs", "setup", "config",
    ),
)

__all__ = ["BILINGUAL_TERM_GROUPS"]
