package io.github.ccch1mneyyy.dsh_app.pet

import android.media.AudioManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PetSoundRulesTest {
    @Test fun onlyClipsOfASoundSetLoad() {
        assertTrue(PetSoundRules.assetOk("assets/pet_sounds/naiwa/daxiao.wav"))
        for (bad in listOf(
            "",
            "assets/pets/naiwa/daxiao.wav",
            "pet_sounds/naiwa/daxiao.wav",
            "assets/pet_sounds/naiwa/daxiao.ogg",
            "assets/pet_sounds/naiwa/daxiao.wav.png",
            "assets/pet_sounds/naiwa/sounds.json",
            "assets/pet_sounds/../pets/whale-girl/pack.wav",
            "assets/pet_sounds/naiwa/../../../shared_prefs/x.wav",
            "assets/pet_sounds/naiwa\\daxiao.wav",
            "assets\\pet_sounds\\naiwa\\daxiao.wav",
            "/assets/pet_sounds/naiwa/daxiao.wav",
            "/data/data/io.github.ccch1mneyyy.dsh_app/cache/pet_sounds/naiwa/daxiao.wav",
        )) {
            assertFalse(bad, PetSoundRules.assetOk(bad))
        }
    }

    @Test fun volumeIsClampedToFull() {
        assertEquals(0.6f, PetSoundRules.volume(0.6)!!, 1e-6f)
        assertEquals(1f, PetSoundRules.volume(1.7)!!, 0f)
        assertEquals(0f, PetSoundRules.volume(-0.3)!!, 0f)
        // A Dart int comes as Integer or Long.
        assertEquals(1f, PetSoundRules.volume(1)!!, 0f)
        assertEquals(0f, PetSoundRules.volume(0L)!!, 0f)
        // Absent: full.
        assertEquals(1f, PetSoundRules.volume(null)!!, 0f)
        assertNull(PetSoundRules.volume("0.5"))
        assertNull(PetSoundRules.volume(true))
        assertNull(PetSoundRules.volume(Double.NaN))
    }

    @Test fun rateStaysWithinSoundPoolsRange() {
        assertEquals(1.08f, PetSoundRules.rate(1.08)!!, 1e-6f)
        assertEquals(0.5f, PetSoundRules.rate(0.1)!!, 0f)
        assertEquals(2f, PetSoundRules.rate(3)!!, 0f)
        assertEquals(2f, PetSoundRules.rate(Double.POSITIVE_INFINITY)!!, 0f)
        // Absent: as recorded.
        assertEquals(1f, PetSoundRules.rate(null)!!, 0f)
        assertNull(PetSoundRules.rate(listOf(1.0)))
        assertNull(PetSoundRules.rate(Double.NaN))
    }

    @Test fun quietOnlyInACall() {
        assertTrue(PetSoundRules.audible(AudioManager.MODE_NORMAL))
        assertTrue(PetSoundRules.audible(AudioManager.MODE_RINGTONE))
        assertFalse(PetSoundRules.audible(AudioManager.MODE_IN_CALL))
        assertFalse(PetSoundRules.audible(AudioManager.MODE_IN_COMMUNICATION))
    }
}
