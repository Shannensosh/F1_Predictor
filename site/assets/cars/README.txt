CUSTOM CONSTRUCTOR CAR PHOTOS  —  Constructors' Championship cards (main dashboard)
==================================================================================

Drop a photo here to use it as the background of a team's championship card
(the top-3 image cards). It fills the card edge-to-edge and OVERRIDES the
automatically-fetched Wikimedia photo — use this to pin an exact current-year
(2026) car profile you control.

FILENAME = the team's constructorId (lowercase), e.g.:
    mclaren.jpg      ferrari.jpg      mercedes.jpg     red_bull.jpg
    aston_martin.jpg alpine.jpg       williams.jpg     rb.jpg
    haas.jpg         audi.jpg         cadillac.jpg
(the team name also works, e.g. "red bull.jpg"; accepted: .jpg .jpeg .png .webp .avif)

• Use a landscape, side-on car shot for the best fit (cropped to ~16:9, right-anchored).
• If no file is here for a team, the card falls back to the auto-fetched 2025/2026
  Commons photo (see CONSTRUCTOR_CAR_QUERY in f1_fetch.py).
• After adding files, run:  python3 build.py
  (the daily GitHub build also picks them up once committed.)

constructorIds match the Ergast/Jolpica ids — if unsure, check data/standings.json.
Only the top-3 teams show a card image, so currently mercedes / ferrari / mclaren
are the ones visible.
