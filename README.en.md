# Pixel Naiwa

[简体中文](README.md) · English

A pixel pet pack for DSH Go, identified as `naiwa`. Its classic yellow body, cream belly, pale green eye rings and gray-brown paws are drawn on a transparent 64×64 canvas, with frame animations for thinking, working, laughing and everyday interactions.

The pack contains **25 animations and 254 frames**. The large image below includes every frame, grouped by animation and labeled with its index and duration, for artwork, timing and animation reference.

[![All 25 Pixel Naiwa animations and 254 frames](docs/assets/naiwa-frames.png)](docs/assets/naiwa-frames.png)

Click the image to view it at full size. Read each group from left to right, then top to bottom. `loop` marks a repeating animation and `once` marks a single playback.

| Context | Animations |
| --- | --- |
| Idle | Breathing and blinking `idle`, looking around `idle-look`, giggling `idle-giggle`, snacking `snack`, and dancing `dance` |
| Thinking | Resting a paw under the chin `thinking` |
| Working | Eating code `eat-code`, eating faster `eat-code-fast`, and feasting `feast`, for 1, 2, and 3 or more running conversations |
| Running subagents | Juggling code blocks `juggle` and juggling more blocks `juggle-many`, for 1 and 2 or more subagents |
| Task complete | Laughing `laugh`, with pointing `laugh-point`, rolling `laugh-roll`, and belly-bouncing `laugh-belly` variants |
| Errors and notifications | Raising paws in surprise `shocked` and waving for attention `alert` |
| Context compaction | Devouring a ribbon of code `devour` |
| Rest and roaming | Sleeping `sleep`, waking and stretching `wake`, and walking `walk` |
| Tapping | Left and right pokes `poke-left` / `poke-right`, and laughter after repeated taps `tickle` |
| Dragging | Crawling and chewing on its belly `prone-eat` |

While awake and idle on the chat page, the pet randomly looks around, giggles, snacks, or dances after a 10–25 second wait between actions. With no active tasks, it falls asleep after 60 seconds without interaction; idle actions do not keep it awake longer.

The front-facing idle frame is the reference for body proportions, upper-arm and forearm lengths, and paw sizes. The body gently stretches and squashes with each action while expressions stay readable. Poke and wake animations finish in the idle pose. The code characters being eaten are drawn into the animation frames.

The following files provide artwork and format references.

| Reference | Location |
| --- | --- |
| Pack manifest and animation sheets | [app/assets/pets/naiwa/](app/assets/pets/naiwa/) |
| Drawing notes, palette and generation commands | [Artwork notes](app/tool/pet_src/naiwa/README.md) |
| Frame drawing script | [draw.py](app/tool/pet_src/naiwa/draw.py) |
| Frame durations and animation mappings | [pet.json](app/tool/pet_src/naiwa/pet.json) |
| DSH Go pet pack format | [Pet design and format](docs/design/pets.md) |

The pixel artwork is by cxsunflower, based on the fan-made Naiwa character. Character rights belong to their respective owners. Sources and asset terms are recorded in the repository notices. [cxsunflower](https://github.com/cxsunflower) · [Character reference](https://github.com/Orliss/nailong) · [Asset notices](ASSETS.md)

The pack uses the pet system in DSH Go, maintained by ccch1mneyyy. Repository code is licensed under AGPL-3.0, with MIT licenses for `sdk/` and `examples/`. Third-party content follows its own notices. [DSH Go](https://github.com/ccch1mneyyy/dsh-Go) · [LICENSE](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
