package io.github.ccch1mneyyy.dsh_app.pet

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.File
import java.nio.file.Files

class PetPackTest {
    private fun anim(name: String, frames: Int, box: String = """{"x": 12, "y": 12, "w": 52, "h": 49}""", loop: Boolean = true, scale: Int = 1): String {
        val b = Regex("\"w\": (\\d+), \"h\": (\\d+)").find(box)!!.groupValues
        return """"$name": {"sheet": "$name.png", "frameW": ${b[1].toInt() * scale}, "frameH": ${b[2].toInt() * scale},
           "cols": 10, "box": $box, "loop": $loop, "ms": ${frames * 100},
           "frames": [${(0 until frames).joinToString { """{"i": $it, "ms": 100}""" }}]}"""
    }

    private val json = """
        {"schema": 1, "id": "whale-girl", "name": "鲸娘", "pixelArt": true, "scale": 1,
         "canvas": {"w": 69, "h": 66}, "anchor": {"x": 35.5, "baseline": 60},
         "contentBox": {"x": 12, "y": 12, "w": 52, "h": 49},
         "animations": {${listOf(
            anim("idle", 21), anim("idle-look", 13), anim("idle-spout", 11), anim("typing", 14),
            anim("music", 8), anim("building", 24, """{"x": 0, "y": 2, "w": 63, "h": 59}"""),
            anim("conducting", 12), anim("happy", 11), anim("thumbs-up", 14), anim("waking", 11, loop = false),
            anim("poke-left", 11, loop = false), anim("drag", 10), anim("swim", 8, """{"x": 2, "y": 11, "w": 66, "h": 55}"""),
        ).joinToString(",")}},
         "states": {"idle": ["idle", "idle-look", "idle-spout"], "working": ["typing"], "juggling": ["music"],
                    "attention": ["happy", "thumbs-up"], "waking": ["waking"], "roam": ["swim"]},
         "tiers": {"working": [{"min": 1, "anim": "typing"}, {"min": 3, "anim": "building"}, {"min": 2, "anim": "music"}],
                   "juggling": [{"min": 2, "anim": "conducting"}, {"min": 1, "anim": "music"}]},
         "timings": {"playMs": {"idle-look": 6580, "idle-spout": 4940, "poke-left": 2110}},
         "reactions": {"tapLeft": "poke-left", "drag": "drag"},
         "roam": {"anim": "swim", "flip": false, "facing": "front"}}
    """.trimIndent()

    @Test fun parsesTheRuntimeFormat() {
        val p = PetPack.parse(json)
        assertEquals("whale-girl", p.id)
        assertEquals("鲸娘", p.name)
        assertTrue(p.pixelArt)
        assertTrue(p.crisp)
        assertEquals(1, p.scale)
        assertEquals(PetBox(12f, 12f, 52f, 49f), p.contentBox)
        assertEquals(2100L, p.animations.getValue("idle").totalMs)
        assertEquals(10, p.animations.getValue("idle").cols)
        assertEquals(3, p.animations.getValue("idle").rows)
        assertFalse(p.animations.getValue("waking").loop)
        assertNull(p.wideBox)
    }

    @Test fun tiersPickTheFirstReachedWhateverTheOrderInTheFile() {
        val p = PetPack.parse(json)
        assertEquals("typing", p.primary("working", 1).name)
        assertEquals("music", p.primary("working", 2).name)
        assertEquals("building", p.primary("working", 3).name)
        assertEquals("building", p.primary("working", 9).name)
        // No tier reached: the state's own primary.
        assertEquals("typing", p.primary("working", 0).name)
        assertEquals("conducting", p.primary("juggling", 2).name)
        assertEquals("music", p.primary("juggling", 1).name)
    }

    @Test fun unknownStatesPlayIdle() {
        val p = PetPack.parse(json)
        assertEquals("idle", p.primary("idle", 0).name)
        assertEquals("idle", p.primary("sweeping", 0).name)
        assertEquals("idle", p.primary("error", 0).name)
        assertEquals("waking", p.primary("waking", 0).name)
    }

    @Test fun idlePoolFallsBackToTheIdleListPastItsPrimary() {
        val p = PetPack.parse(json)
        assertEquals(listOf("idle-look", "idle-spout"), p.idlePool.map { it.anim.name })
        assertEquals(listOf(1, 1), p.idlePool.map { it.weight })
        assertEquals(listOf(6580L, 4940L), p.idlePool.map { it.ms })
    }

    @Test fun idlePoolAsPackFormatWritesIt() {
        val p = PetPack.parse(
            json.replace(
                "\"reactions\":",
                """"idlePool": {"everyMs": {"mean": 120000, "min": 45000, "max": 300000},
                               "anims": [{"anim": "idle-look", "ms": 6580, "weight": 2}, {"anim": "idle-spout", "ms": 4940, "weight": 1}]},
                   "bonus": {},
                   "reactions":""",
            ),
        )
        assertEquals(listOf("idle-look" to 6580L, "idle-spout" to 4940L), p.idlePool.map { it.anim.name to it.ms })
        assertEquals(listOf(2, 1), p.idlePool.map { it.weight })
        // An empty bonus means none, not the state list.
        assertNull(p.bonusOf("attention", 0))
        assertEquals("idle", p.primary("idle", 0).name)
    }

    @Test fun idlePoolAndBonusFromTheDesignFields() {
        val withPool = json.replace(
            "\"reactions\":",
            """"idlePool": [{"anim": "idle", "ms": 4800, "weight": 3}, {"anim": "idle-spout", "ms": 6400}],
               "bonus": {"attention": {"anims": ["thumbs-up"], "chance": 0.2}},
               "hitBoxes": {"wide": {"x": 6, "y": 14, "w": 40, "h": 34}},
               "reactions":""",
        )
        val p = PetPack.parse(withPool)
        assertEquals(listOf("idle" to 4800L, "idle-spout" to 6400L), p.idlePool.map { it.anim.name to it.ms })
        assertEquals(listOf(3, 1), p.idlePool.map { it.weight })
        assertEquals(0.2f, p.bonusOf("attention", 0)!!.chance, 1e-6f)
        assertEquals(PetBox(6f, 14f, 40f, 34f), p.wideBox)
        // The window at rest adds the idle picture's cell (12, 12, 52 × 49): x 6…64, y 12…61.
        assertEquals(PetBox(6f, 12f, 58f, 49f), p.windowBox())
    }

    /** As the chat page's hitBoxFor (pet_pack.dart): byAnim over sleepingAnims over wideAnims, else default, else the body. */
    @Test fun hitBoxesAsTheChatPageReadsThem() {
        val p = PetPack.parse(json.replace(
            "\"reactions\":",
            """"hitBoxes": {"default": {"x": 13, "y": 12, "w": 50, "h": 48}, "wide": {"x": 10, "y": 12, "w": 53, "h": 48},
                            "sleeping": {"x": 12, "y": 12, "w": 51, "h": 49},
                            "byAnim": {"typing": {"x": 2, "y": 12, "w": 66, "h": 54}},
                            "wideAnims": ["typing", "music"], "sleepingAnims": ["music"]},
               "reactions":""",
        ))
        fun hit(name: String) = p.hitBoxFor(p.animations.getValue(name))
        assertEquals(PetBox(2f, 12f, 66f, 54f), hit("typing"))
        assertEquals(PetBox(12f, 12f, 51f, 49f), hit("music"))
        assertEquals(PetBox(13f, 12f, 50f, 48f), hit("idle"))
        // No hitBoxes at all: the body.
        val bare = PetPack.parse(json)
        assertEquals(bare.contentBox, bare.hitBoxFor(bare.animations.getValue("typing")))
    }

    /** The chat page's `sounds` and `snack` (docs/design/naiwa-pet.md §5): the overlay reads past them. */
    @Test fun soundsAndSnackChangeNothingElse() {
        val p = PetPack.parse(json.replace(
            "\"reactions\":",
            """"sounds": "naiwa",
               "snack": {"mouth": {"x": 33, "y": 31}, "every": {"typing": 700, "building": 200, "eat-code": 380}},
               "reactions":""",
        ))
        val bare = PetPack.parse(json)
        assertEquals(bare.id, p.id)
        assertEquals(bare.contentBox, p.contentBox)
        assertEquals(bare.animations, p.animations)
        assertEquals(bare.states, p.states)
        assertEquals(bare.tiers, p.tiers)
        assertEquals(bare.reactions, p.reactions)
        assertEquals(bare.playMs, p.playMs)
        assertEquals(bare.idlePool, p.idlePool)
        assertEquals(bare.windowBox(), p.windowBox())
    }

    @Test fun aLegacySizeScaleIsIgnored() {
        val p = PetPack.parse(json.replace("\"reactions\":", "\"sizeScale\": 2, \"reactions\":"))
        // A 49 px body at density 3: 1 / 2 / 3 physical px per art px, as without the key.
        assertEquals(listOf(1, 2, 3), PetSize.values().map { p.devicePixels(it, 3f) })
    }

    @Test fun bonusFromTheStateListAtAThird() {
        val p = PetPack.parse(json)
        val b = p.bonusOf("attention", 0)!!
        assertEquals(listOf("thumbs-up"), b.anims.map { it.name })
        assertEquals(1f / 3, b.chance, 1e-6f)
        assertNull(p.bonusOf("idle", 0))
        assertNull(p.bonusOf("working", 2))
    }

    @Test fun windowWithoutWideBoxCoversEveryStateButRoam() {
        val p = PetPack.parse(json)
        // building reaches x 0 and y 2; swim (roam) would reach the canvas bottom but doesn't count.
        val w = p.windowBox()
        assertEquals(0f, w.x)
        assertEquals(2f, w.y)
        assertEquals(64f, w.right)
        assertEquals(61f, w.bottom)
    }

    @Test fun screenScaleMatchesTheAppForEverySize() {
        val p = PetPack.parse(json)
        // The app's petDevicePixels (pet_sprite.dart, and pet_pixel_test.dart's ratio list): whole
        // physical px per art px, 22/30/40 dp over a 49 px body, the three sizes at least one apart.
        val expected = mapOf(
            2.0f to listOf(1, 2, 3),
            2.625f to listOf(1, 2, 3),
            2.75f to listOf(1, 2, 3),
            3.0f to listOf(1, 2, 3),
            3.5f to listOf(2, 3, 4),
        )
        for ((density, ks) in expected) {
            assertEquals("at $density", ks.map { it.toFloat() }, PetSize.values().map { p.screenScale(it, density) })
        }
        // A high-ratio pack is still pixel art: always whole.
        val hiRes = PetPack.parse(
            """{"schema": 1, "id": "deepy-whale", "pixelArt": true, "scale": 5, "canvas": {"w": 52, "h": 52},
                "contentBox": {"x": 12, "y": 26, "w": 36, "h": 22},
                "animations": {"idle": {"sheet": "idle.png", "frameW": 180, "frameH": 120, "cols": 21,
                  "box": {"x": 12, "y": 26, "w": 36, "h": 24}, "frames": [{"i": 0, "ms": 50}]}}}""",
        )
        assertFalse(hiRes.crisp)
        assertEquals(4f, hiRes.screenScale(PetSize.MEDIUM, 2.625f))
        // A smooth (non-pixel-art) pack draws at the target body height instead.
        val smooth = PetPack.parse(json.replace("\"pixelArt\": true", "\"pixelArt\": false"))
        assertEquals(30 * 2.625f / 49, smooth.screenScale(PetSize.MEDIUM, 2.625f), 1e-4f)
        assertEquals(22f, PetSize.SMALL.dp)
        assertEquals(30f, PetSize.MEDIUM.dp)
        assertEquals(40f, PetSize.LARGE.dp)
        assertEquals(PetSize.MEDIUM, PetSize.fromName(null))
        assertEquals(PetSize.LARGE, PetSize.fromName("large"))
        assertEquals(PetSize.SMALL, PetSize.fromName("small"))
        assertEquals(PetSize.MEDIUM, PetSize.fromName("medium"))
    }

    /** The same table as `pet_pixel_test.dart` (the app) and `test/pets/pet_pixel_test.dart`: a drift on either side is caught. */
    @Test fun screenScaleMatchesTheAppForTheShippedPacks() {
        val packs = shipped()
        val expected = mapOf(
            "whale-girl" to mapOf(
                2.0f to listOf(1, 2, 3),
                2.625f to listOf(1, 2, 3),
                2.75f to listOf(1, 2, 3),
                3.0f to listOf(1, 2, 3),
                3.5f to listOf(2, 3, 4),
            ),
            "deepy-whale" to mapOf(
                2.0f to listOf(2, 3, 4),
                2.625f to listOf(3, 4, 5),
                2.75f to listOf(3, 4, 5),
                3.0f to listOf(3, 4, 5),
                3.5f to listOf(4, 5, 6),
            ),
        )
        for ((id, byDensity) in expected) {
            val p = packs.getValue(id)
            for ((density, ks) in byDensity) {
                assertEquals("$id at $density", ks.map { it.toFloat() }, PetSize.values().map { p.screenScale(it, density) })
            }
        }
    }

    @Test fun reactionsAndPlayTimes() {
        val p = PetPack.parse(json)
        assertEquals("poke-left", p.reaction("tapLeft")?.name)
        assertNull(p.reaction("tapRight"))
        assertEquals(2110L, p.playMsOf(p.animations.getValue("poke-left")))
        // Without playMs: two cycles of a loop.
        assertEquals(2 * 800L, p.playMsOf(p.animations.getValue("music")))
    }

    @Test fun brokenPacksAreRejected() {
        val bads = listOf(
            "[]",
            json.replace("\"schema\": 1", "\"schema\": 2"),
            json.replace("\"scale\": 1,", ""),
            json.replace("\"id\": \"whale-girl\",", ""),
            // A state naming a missing animation.
            json.replace("\"waking\": [\"waking\"]", "\"waking\": [\"yawn\"]"),
            json.replace("\"tapLeft\": \"poke-left\"", "\"tapLeft\": \"poke\""),
            json.replace("\"anim\": \"swim\"", "\"anim\": \"fly\""),
            // A zero frame time, a cell size that isn't box × scale, a sheet outside the folder.
            json.replace("{\"i\": 0, \"ms\": 100}", "{\"i\": 0, \"ms\": 0}"),
            json.replace("\"frameW\": 52,", "\"frameW\": 53,"),
            json.replace("\"sheet\": \"idle.png\"", "\"sheet\": \"../idle.png\""),
        )
        for (bad in bads) {
            try {
                PetPack.parse(bad)
                fail("accepted: ${bad.take(80)}")
            } catch (_: PetPackException) {
            }
        }
    }

    /** The bundled packs, by id, with their folder. */
    private fun shippedDirs(): Map<String, Pair<File, PetPack>> {
        val root = generateSequence(File("").absoluteFile) { it.parentFile }.map { File(it, "app/assets/pets") }.firstOrNull { it.isDirectory }
            ?: generateSequence(File("").absoluteFile) { it.parentFile }.map { File(it, "assets/pets") }.firstOrNull { it.isDirectory }
            ?: return emptyMap()
        return root.listFiles { f -> File(f, "pack.json").isFile }.orEmpty().associate { dir ->
            dir.name to (dir to PetPack.parse(File(dir, "pack.json").readText()))
        }
    }

    private fun shipped(): Map<String, PetPack> = shippedDirs().mapValues { it.value.second }

    /** The bundled packs parse, and every sheet fits the decode budget at the scale it is drawn. */
    @Test fun shippedPacksParse() {
        for ((id, dirAndPack) in shippedDirs()) {
            val (dir, p) = dirAndPack
            assertEquals(id, p.id)
            for (a in p.animations.values) {
                assertTrue("${p.id}/${a.sheet}", File(dir, a.sheet).isFile)
                for (size in PetSize.values()) {
                    val k = p.screenScale(size, 3.5f)
                    val r = PetSprites.perLogicalFor(p.scale, k, a, PetSprites.SHEET_BYTES)
                    val bytes = 4L * minOf(a.cols, a.cells) * a.box.w.toLong() * r * a.rows * a.box.h.toLong() * r
                    assertTrue("${p.id}/${a.name} r=$r $bytes", r == 1 || bytes <= PetSprites.SHEET_BYTES)
                }
            }
        }
    }

    // ---- installed packs (docs/design/pet-packs.md §4) -----------------------------------------

    /** A one-animation pack, as `pack.json`; [name] tells the installed copy from the bundled one. */
    private fun packJson(id: String, name: String = id): String = """
        {"schema": 1, "id": "$id", "name": "$name", "scale": 1,
         "canvas": {"w": 69, "h": 66}, "contentBox": {"x": 12, "y": 12, "w": 52, "h": 49},
         "animations": {"idle": {"sheet": "idle.png", "frameW": 52, "frameH": 49, "cols": 1,
           "box": {"x": 12, "y": 12, "w": 52, "h": 49}, "frames": [{"i": 0, "ms": 100}]}},
         "states": {"idle": ["idle"]}}
    """.trimIndent()

    private fun tempDir(): File = Files.createTempDirectory("pet-pack").toFile().apply { deleteOnExit() }

    private fun bundled(vararg files: Pair<String, String>): (String) -> java.io.InputStream? =
        { name -> files.toMap()[name]?.toByteArray()?.let { ByteArrayInputStream(it) } }

    /** [root]/<id>/pack with [manifest] and the sheet at [sheet]. */
    private fun install(root: File, id: String, manifest: String, sheet: String? = "sheets/idle.png"): File {
        val dir = File(root, "$id/pack").apply { mkdirs() }
        File(dir, "pack.json").writeText(manifest)
        if (sheet != null) {
            File(dir, sheet).apply { parentFile!!.mkdirs() }.writeBytes(byteArrayOf(1, 2, 3))
        }
        return dir
    }

    private fun read(source: ((String) -> java.io.InputStream?)?): String =
        source!!("pack.json")!!.use { it.readBytes().toString(Charsets.UTF_8) }

    @Test fun theInstalledCopyComesBeforeTheBundledOne() {
        val root = tempDir()
        install(root, "deepy-whale", packJson("deepy-whale", "安装版"))
        val source = PetPackFiles.source(root, "deepy-whale", bundled("pack.json" to packJson("deepy-whale", "内置版")), null)
        assertTrue(read(source).contains("安装版"))
        assertEquals("安装版", PetPackFiles.installed(root, "deepy-whale")?.pack?.name)
    }

    @Test fun aMissingOrEmptyRootFallsBackToTheAssets() {
        val source = PetPackFiles.source(tempDir(), "deepy-whale", bundled("pack.json" to packJson("deepy-whale", "内置版")), null)
        assertTrue(read(source).contains("内置版"))
        assertNull(PetPackFiles.installed(tempDir(), "deepy-whale"))
        assertNull(PetPackFiles.installed(null, "deepy-whale"))
        assertNull(PetPackFiles.source(null, "deepy-whale", null, null))
    }

    @Test fun brokenAndHalfPacksFallBackWithoutThrowing() {
        val cases = listOf(
            "" to "sheets/idle.png",
            "[]" to "sheets/idle.png",
            packJson("deepy-whale").replace("\"schema\": 1", "\"schema\": 9") to "sheets/idle.png",
            packJson("other-pet") to "sheets/idle.png",
            packJson("deepy-whale") to null,
        )
        for ((manifest, sheet) in cases) {
            val root = tempDir()
            install(root, "deepy-whale", manifest, sheet)
            assertNull("manifest=${manifest.take(24)} sheet=$sheet", PetPackFiles.installed(root, "deepy-whale"))
            val source = PetPackFiles.source(root, "deepy-whale", bundled("pack.json" to packJson("deepy-whale", "内置版")), null)
            assertTrue(read(source).contains("内置版"))
        }
        // A manifest that is a directory, not a file.
        val root = tempDir()
        val dir = File(root, "deepy-whale/pack/pack.json").apply { mkdirs() }
        assertTrue(dir.isDirectory)
        assertNull(PetPackFiles.installed(root, "deepy-whale"))
    }

    @Test fun aRootThatIsAFileOrASymlinkIsNoRoot() {
        val file = File(tempDir(), "pets").apply { writeText("x") }
        assertNull(PetPackFiles.installed(file, "deepy-whale"))
    }

    @Test fun onlyDataFilesInsideThePackAreRead() {
        val dir = install(tempDir(), "deepy-whale", packJson("deepy-whale"))
        File(dir, "sounds").mkdirs()
        assertNotNull(PetPackFiles.file(dir, "pack.json"))
        assertNotNull(PetPackFiles.file(dir, "sheets/idle.png"))
        File(dir, "sounds/daxiao.wav").writeBytes(byteArrayOf(1))
        assertNotNull(PetPackFiles.file(dir, "sounds/daxiao.wav"))
        for (bad in listOf(
            "../pack.json", "/etc/passwd", "sheets/../../idle.png", "../../../idle.png",
            "evil.js", "evil.so", "evil.apk", "evil.dex", "evil.jar", "nested/idle.png",
            "sheets/evil.js", ".hidden.png", "idle.PNG", "",
        )) {
            assertNull(bad, PetPackFiles.file(dir, bad))
        }
        assertNull(PetPackFiles.file(dir, "missing.png"))
    }

    @Test fun illegalIdsAreRefused() {
        for (bad in listOf("", "..", "../x", "/abs", "A-upper", "with space", "奶蛙", "a/b", "a".repeat(65))) {
            assertFalse(bad, PetPackFiles.idOk(bad))
        }
        for (good in listOf("naiwa", "deepy-whale", "whale-girl2")) assertTrue(PetPackFiles.idOk(good))
        // Even a valid directory is not found under an illegal id.
        val root = tempDir()
        install(root, "deepy-whale", packJson("deepy-whale"))
        assertNull(PetPackFiles.installed(root, "../deepy-whale"))
    }

    @Test fun symbolicLinksOutOfThePackAreRefused() {
        val outside = tempDir()
        File(outside, "idle.png").writeBytes(byteArrayOf(1))
        val dir = tempDir()
        val linkedDir = try {
            Files.createSymbolicLink(File(dir, "sheets").toPath(), outside.toPath())
            true
        } catch (_: Exception) {
            false
        }
        if (linkedDir) {
            assertNull(PetPackFiles.file(dir, "sheets/idle.png"))
            // A sheet that is a link fails the whole pack.
            File(dir, "pack.json").writeText(packJson("deepy-whale"))
            assertNull(PetPackFiles.installed(dir, "deepy-whale"))
        }
        val root = tempDir()
        val packDir = File(root, "linked/pack").apply { mkdirs() }
        File(packDir, "pack.json").writeText(packJson("linked"))
        val linkedFile = try {
            Files.createSymbolicLink(File(packDir, "idle.png").toPath(), File(outside, "idle.png").toPath())
            true
        } catch (_: Exception) {
            false
        }
        if (linkedFile) assertNull(PetPackFiles.installed(root, "linked"))
    }

    @Test fun withoutAPushedRootBehaviourIsUnchanged() {
        val legacy = tempDir()
        File(legacy, "pack.json").writeText(packJson("deepy-whale", "旧目录"))
        File(legacy, "idle.png").writeBytes(byteArrayOf(1))
        // Assets first, as before.
        val both = PetPackFiles.source(null, "deepy-whale", bundled("pack.json" to packJson("deepy-whale", "内置版")), legacy)
        assertTrue(read(both).contains("内置版"))
        // Then the flat `files/pets/<id>/` directory.
        val legacyOnly = PetPackFiles.source(null, "deepy-whale", null, legacy)
        assertTrue(read(legacyOnly).contains("旧目录"))
        // And the assets still work with no directory at all.
        val assetsOnly = PetPackFiles.source(null, "deepy-whale", bundled("pack.json" to packJson("deepy-whale", "内置版")), null)
        assertTrue(read(assetsOnly).contains("内置版"))
    }

}
