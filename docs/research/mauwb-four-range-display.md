# Four-distance MaUWB display

## Finding

An MaUWB firmware V1.1.6 `AT+RANGE` record contains two aligned, eight-item
tuples: `range` and `ancid`.  Each pair at the same tuple index describes one
tag-to-anchor observation.  The firmware manual labels these fields as the
distance to anchors 0 through 7 and the device ID of the corresponding
tag-to-anchor pair.

Build a frame by zipping the tuples, retaining only pairs where `ancid` is
nonnegative and `range` is positive, and converting centimetres to metres.
Use `ancid` to select and order the four display positions.  Do not use the
tuple index as the deployed anchor identity.

For a configured order of anchor IDs `1, 2, 3, 4`, a complete display frame
would be exactly:

```text
1.02 1.06 1.09 0.98
```

The recorder should emit that line only after it has all four requested
anchor IDs for the same tag and sequence.  A missing anchor should make the
frame incomplete rather than be represented as `0`, since a zero range in the
report is a placeholder rather than a valid measurement.

## Implications for the current collector

The A4 screenshot shows one valid pair, `range:102` with `ancid:4`, which is
`1.02` metres for anchor 4.  It does not establish the intended identities or
order of the other three display values.  Keep mapping by actual anchor ID;
the requested output order must be configured explicitly.

Keep `mask` as raw metadata.  The V1.1.6 manual calls it a hexadecimal
significance bit but does not document a bit-to-anchor mapping, so it is not a
safe source for determining the order or presence of a distance.

## Sources

- [Makerfabs MaUWB Firmware V1.1.6 manual, AT+RANGE section (pp. 16-17)](https://github.com/Makerfabs/MaUWB_ESP32S3-with-STM32-AT-Command/tree/main/example/Firmware%20V1.1.6%20Manual%26%20Demo)
- [Makerfabs update-frequency test](https://www.makerfabs.com/blog/post/mauwb-update-frequency-test) — documents that each anchor outputs the same system data and notes the V1.1.6 report change.
- [Makerfabs DW3000 multi-anchor example](https://github.com/Makerfabs/Makerfabs-ESP32-UWB-DW3000/blob/main/example/Multi%20Anchor%20%2B%20Multi%20Tag/tag/tag.ino) — corroborates aligned range and anchor-ID tuples, but is a different firmware and is not authority for V1.1.6 mask semantics.
