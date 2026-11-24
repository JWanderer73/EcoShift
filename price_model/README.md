# price_model

The day-ahead price model from the modeling team, copied unchanged from their repo
(github.com/JWanderer73/ecoshift, branch `Harkirat-Hattar`, commit `7f467d9`, 2026-11-22)
(`price_windows/` and the `src/` modules it imports). The cloud code in `src/carbon/price/`
calls it; nothing here is edited. To update the model, replace these folders with the
modeling team's newer copy.

`.env.example` and `requirements.txt` are empty marker files: the model finds its "repo root" by
looking for them.
