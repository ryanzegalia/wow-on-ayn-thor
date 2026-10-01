package com.ff.wowlaunch;

import android.app.Activity;
import android.os.Bundle;

/**
 * Tile trampoline for every World of Warcraft flavor on the AYN Thor.
 *
 * WHY THIS EXISTS: all flavors run in ONE GameNative custom-game container (app_id
 * 1285328983, one Wine prefix carrying the patched ntdll/winevulkan and my DXVK build), and the
 * only exe selector GameNative has is "executablePath" in that container's .container file.
 * LAUNCH_GAME has no exe extra. So each tile goes through here, and the on-device launcher
 * /data/adb/wow/wowlaunch.sh does the work: mirror the shared config into the flavor, point
 * the container at its ARM64 exe, re-pin the driver, fire LAUNCH_GAME.
 * Source of the launcher: launcher/scripts/wowlaunch.sh (deployed by tools/wow_mirror.py).
 *
 * The alias (.Retail / .Classic / .Beta) selects the flavor.
 */
public class LaunchActivity extends Activity {

    private static final String LAUNCHER = "/data/adb/wow/wowlaunch.sh";

    private static String flavorForAlias(String cls) {
        if (cls == null) return "retail";
        if (cls.endsWith(".Classic")) return "classic";
        if (cls.endsWith(".Beta"))    return "beta";
        return "retail";
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String cls = null;
        if (getIntent() != null && getIntent().getComponent() != null) {
            cls = getIntent().getComponent().getClassName();
        }
        String flavor = flavorForAlias(cls);

        // Detached (setsid, backgrounded): the first launch of a flavor copies addons over FUSE
        // and can take longer than an activity may block its UI thread. su returns at once.
        // --mount-master: another app's /data/data is only visible in the global namespace.
        String cmd = "setsid sh " + LAUNCHER + " " + flavor + " </dev/null >/dev/null 2>&1 &";
        try {
            Runtime.getRuntime().exec(new String[]{"su", "--mount-master", "-c", cmd}).waitFor();
        } catch (Exception e) {
            try {
                Runtime.getRuntime().exec(new String[]{"am", "start", "-n",
                    "app.gamenative/.MainActivity"}).waitFor();
            } catch (Exception ignored) {}
        }
        finish();
    }
}
