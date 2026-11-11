# TODO

- [investigate] 2026-11-10: option C has no printed test enclosure (the old one was built around face screws), so the captain's F2 "home printer for first tests" is now only the coupon and the small printed parts. A printed cover and base matching the metal split would let the whole deck be fitted before the SendCutSend order (`case/README.md`, Not verified).
- [investigate] 2026-11-10: nothing locates the LCD-5 sideways in option C except the cradle's foam and pressure (`case/helm_case/printed.py` `cradle`); tabs on the cradle's right and back edges would, if a bench fit shows the module sliding.
- [investigate] 2026-11-10: SHOW ME is lit only when an item has a herdr pane (`_actions` in `helm/bridge/items.py`), so an item with a PR or report but no pane cannot open them from the deck. Adding `focus` when an item has a PR URL or a `data/<task>/report.md` (a stat per rebuild) would light it; the bridge already handles a tap with no pane.
