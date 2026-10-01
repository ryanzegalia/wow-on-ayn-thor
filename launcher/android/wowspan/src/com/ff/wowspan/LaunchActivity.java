package com.ff.wowspan;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.*;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.util.concurrent.*;

/** Native, controller-first front end. Root preparation and Wine never run on the UI thread. */
public final class LaunchActivity extends Activity {
    private static final int INK = 0xff101113, PANEL = 0xff191a1c, GOLD = 0xffc8a96b;
    private static final int CREAM = 0xffefdfbf, MUTED = 0xffa99f8c, RED = 0xff761f24;
    private static final String SCRIPT = "/data/adb/wow/wowgo.sh";
    private static final String STATUS = "/data/adb/wow/launch-status";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final GameTile[] tiles = new GameTile[3];
    private final String[] flavors = {"retail", "classic", "beta"};
    private final String[] titles = {"Retail", "Classic", "Forever"};
    private final String[] subtitles = {"MIDNIGHT", "MISTS OF PANDARIA", "BETA"};
    private SharedPreferences prefs;
    private LinearLayout root;
    private TextView status, detail, modeHint;
    private Button direct, bnet;
    private ProgressBar progress;
    private boolean resumed, busy, polling, submitting, controllerNavigating;
    private int controllerFocus;
    private String mode, generation = "", phase = "idle";
    private long submittedAt;
    private Typeface heading;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN, WindowManager.LayoutParams.FLAG_FULLSCREEN);
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN
            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        prefs = getSharedPreferences("launcher", MODE_PRIVATE);
        mode = "bnet".equals(prefs.getString("mode", "direct")) ? "bnet" : "direct";
        generation = prefs.getString("generation", "");
        heading = Typeface.create("serif", Typeface.BOLD);
        try { heading = Typeface.createFromAsset(getAssets(), "heading.ttf"); } catch (RuntimeException ignored) { }
        buildMenu();
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView text(String value, int size, int color, boolean title) {
        TextView v = new TextView(this);
        v.setText(value); v.setTextSize(size); v.setTextColor(color);
        if (title) v.setTypeface(heading);
        v.setIncludeFontPadding(false);
        return v;
    }
    private LinearLayout.LayoutParams lp(int w, int h) { return new LinearLayout.LayoutParams(w, h); }
    private Button button(String label) {
        Button b = new Button(this);
        b.setText(label); b.setAllCaps(false); b.setTextSize(15); b.setTextColor(CREAM);
        b.setTypeface(heading); b.setPadding(dp(16), 0, dp(16), 0);
        b.setMinimumWidth(0); b.setMinimumHeight(0);
        b.setBackground(new MenuFrame(true, "Direct".equals(label) ? 3 : 4));
        b.setBackgroundTintList(null); b.setStateListAnimator(null);
        return b;
    }
    private void buildMenu() {
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(32), dp(20), dp(32), dp(16)); root.setBackground(new MenuFrame(false));
        setContentView(root);
        LinearLayout header = new LinearLayout(this); header.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout words = new LinearLayout(this); words.setOrientation(LinearLayout.VERTICAL);
        TextView eyebrow = text("WORLD OF WARCRAFT", 11, GOLD, false); eyebrow.setLetterSpacing(.18f);
        words.addView(eyebrow);
        TextView title = text("Choose your world", 27, CREAM, true);
        LinearLayout.LayoutParams titleLp = lp(-1, -2); titleLp.topMargin = dp(4); words.addView(title, titleLp);
        header.addView(words, new LinearLayout.LayoutParams(0, -2, 1));
        LinearLayout modes = new LinearLayout(this);
        direct = button("Direct"); bnet = button("Battle.net");
        direct.setId(View.generateViewId()); bnet.setId(View.generateViewId());
        modes.addView(direct, lp(dp(112), dp(40))); modes.addView(bnet, lp(dp(128), dp(40)));
        header.addView(modes); root.addView(header);
        modeHint = text("", 11, MUTED, false); modeHint.setGravity(Gravity.RIGHT);
        LinearLayout.LayoutParams hintLp = lp(-1, dp(24)); hintLp.topMargin = dp(4); root.addView(modeHint, hintLp);
        direct.setOnClickListener(v -> setMode("direct")); bnet.setOnClickListener(v -> setMode("bnet"));
        LinearLayout row = new LinearLayout(this); row.setBaselineAligned(false);
        LinearLayout.LayoutParams rowLp = new LinearLayout.LayoutParams(-1, 0, 1); rowLp.topMargin = dp(8); rowLp.bottomMargin = dp(16);
        root.addView(row, rowLp);
        for (int i = 0; i < tiles.length; i++) {
            final int index = i;
            GameTile tile = new GameTile(i); tiles[i] = tile;
            tile.setId(View.generateViewId()); tile.setFocusable(true); tile.setClickable(true);
            tile.setContentDescription("Launch " + titles[i] + " in dual screen");
            tile.setOnClickListener(v -> launch(index));
            LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(0, -1, 1);
            if (i > 0) p.leftMargin = dp(16); row.addView(tile, p);
            tile.setNextFocusUpId(bnet.getId());
        }
        for (int i = 0; i < tiles.length; i++) {
            tiles[i].setNextFocusLeftId(tiles[Math.max(0, i - 1)].getId());
            tiles[i].setNextFocusRightId(tiles[Math.min(2, i + 1)].getId());
        }
        direct.setNextFocusDownId(tiles[0].getId()); bnet.setNextFocusDownId(tiles[2].getId());
        direct.setNextFocusRightId(bnet.getId()); bnet.setNextFocusLeftId(direct.getId());
        LinearLayout footer = new LinearLayout(this); footer.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout messages = new LinearLayout(this); messages.setOrientation(LinearLayout.VERTICAL);
        status = text("Ready for adventure", 16, CREAM, true); messages.addView(status);
        detail = text("Dual screen  /  Shared controls and layout", 11, MUTED, false);
        LinearLayout.LayoutParams detailLp = lp(-1, -2); detailLp.topMargin = dp(4); messages.addView(detail, detailLp);
        footer.addView(messages, new LinearLayout.LayoutParams(0, -2, 1));
        TextView controls = text("D-pad  Select     A  Play     B  Back", 11, MUTED, false); footer.addView(controls);
        root.addView(footer, lp(-1, dp(48)));
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setIndeterminate(true); progress.setIndeterminateTintList(android.content.res.ColorStateList.valueOf(GOLD));
        progress.setVisibility(View.INVISIBLE); root.addView(progress, lp(-1, dp(4)));
        setMode(mode);
        tiles[Math.max(0, Math.min(2, prefs.getInt("flavor", 0)))].requestFocus();
    }

    private void setMode(String value) {
        if (busy) return;
        mode = value; prefs.edit().putString("mode", mode).apply();
        direct.setSelected("direct".equals(mode)); bnet.setSelected("bnet".equals(mode));
        direct.invalidate(); bnet.invalidate();
        modeHint.setText("bnet".equals(mode) ? "Launch through Battle.net" : "Open WoW directly and sign in");
    }
    private void showStatus(String next, String message) {
        phase = next;
        busy = !("idle".equals(next) || "error".equals(next) || "finished".equals(next));
        direct.setEnabled(!busy); bnet.setEnabled(!busy);
        for (GameTile tile : tiles) { tile.setEnabled(true); tile.invalidate(); }
        progress.setVisibility(busy && !"running".equals(next) ? View.VISIBLE : View.INVISIBLE);
        status.setText(message); status.setTextColor("error".equals(next) ? 0xffe89b85 : CREAM);
        if ("error".equals(next)) detail.setText("No game was stopped. Select a world to retry.");
        else if ("running".equals(next)) detail.setText("Select a world to return to the running game. Exit from its game menu.");
        else if (busy) detail.setText("Preparing your adventure. The game opens on the top screen.");
        else detail.setText("Dual screen  /  Shared controls and layout");
    }
    private void launch(int index) {
        // The backend owns the lock. A stale busy frame after returning must not eat Play.
        if (submitting) return;
        prefs.edit().putInt("flavor", index).apply();
        generation = Long.toString(System.currentTimeMillis());
        prefs.edit().putString("generation", generation).apply();
        final String request = generation, selectedMode = mode;
        submittedAt = SystemClock.elapsedRealtime(); submitting = true;
        showStatus("preparing", "Preparing " + titles[index] + "...");
        worker.execute(() -> {
            String command = "test -f " + SCRIPT + " || exit 41; "
                + "setsid sh " + SCRIPT + " " + flavors[index] + " " + selectedMode + " " + request
                + " </dev/null >/dev/null 2>&1 &";
            final ShellResult r = shell(command, 20);
            main.post(() -> {
                submitting = false;
                if (isFinishing() || isDestroyed()) return;
                if (r.code != 0) showStatus("error", r.code == 41
                    ? "Launcher preparation is not installed" : r.code == -1 ? "The root request timed out. Check Magisk, then retry."
                    : "Could not start preparation. Check root access in Magisk.");
            });
        });
    }
    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (!resumed) return;
            if (!polling && !submitting) {
                polling = true;
                worker.execute(() -> {
                    final ShellResult r = shell("test ! -f " + SCRIPT + " || sh " + SCRIPT + " --status", 8);
                    main.post(() -> {
                        polling = false;
                        if (!resumed || isDestroyed()) return;
                        if (r.code == 0 && !r.text.trim().isEmpty()) {
                            String[] lines = r.text.replace("\r", "").split("\n");
                            if (lines.length >= 3 && (generation.isEmpty() || generation.equals(lines[2]) || !busy)) {
                                generation = lines[2]; prefs.edit().putString("generation", generation).apply();
                                showStatus(lines[0], lines[1]);
                            } else if (busy && SystemClock.elapsedRealtime() - submittedAt > 30000 && "preparing".equals(phase)) {
                                showStatus("error", "The launcher did not acknowledge this request");
                            }
                        } else if (busy && SystemClock.elapsedRealtime() - submittedAt > 30000 && "preparing".equals(phase)) {
                            showStatus("error", "Could not read launcher progress");
                        }
                    });
                });
            }
            main.postDelayed(this, 2000);
        }
    };
    @Override protected void onResume() { super.onResume(); resumed = true; controllerNavigating = false; main.removeCallbacks(tick); main.post(tick); }
    @Override protected void onPause() { resumed = false; main.removeCallbacks(tick); super.onPause(); }
    @Override protected void onDestroy() { resumed = false; main.removeCallbacksAndMessages(null); worker.shutdownNow(); super.onDestroy(); }
    private void redrawFocus() {
        direct.invalidate(); bnet.invalidate();
        for (GameTile tile : tiles) tile.invalidate();
    }
    @Override public boolean dispatchTouchEvent(MotionEvent e) {
        if (e.getActionMasked() == MotionEvent.ACTION_DOWN) { controllerNavigating = false; redrawFocus(); }
        return super.dispatchTouchEvent(e);
    }
    @Override public boolean dispatchKeyEvent(KeyEvent e) {
        int key = e.getKeyCode();
        if (key == KeyEvent.KEYCODE_BUTTON_B) {
            if (e.getAction() == KeyEvent.ACTION_UP) onBackPressed(); return true;
        }
        boolean activate = key == KeyEvent.KEYCODE_BUTTON_A || key == KeyEvent.KEYCODE_DPAD_CENTER;
        boolean direction = key == KeyEvent.KEYCODE_DPAD_UP || key == KeyEvent.KEYCODE_DPAD_DOWN
            || key == KeyEvent.KEYCODE_DPAD_LEFT || key == KeyEvent.KEYCODE_DPAD_RIGHT;
        if (!activate && !direction) return super.dispatchKeyEvent(e);
        // Own the five-control navigation order: Android touch-mode focus must never change A's target.
        if (!controllerNavigating) {
            controllerNavigating = true;
            controllerFocus = Math.max(0, Math.min(2, prefs.getInt("flavor", 0)));
        }
        // Android may consume the first D-pad DOWN when leaving touch mode; UP still reaches this handler.
        if (e.getAction() == KeyEvent.ACTION_UP && direction) {
            if (key == KeyEvent.KEYCODE_DPAD_UP && controllerFocus < 3) controllerFocus = "bnet".equals(mode) ? 4 : 3;
            else if (key == KeyEvent.KEYCODE_DPAD_DOWN && controllerFocus >= 3) controllerFocus = Math.max(0, Math.min(2, prefs.getInt("flavor", 0)));
            else if (key == KeyEvent.KEYCODE_DPAD_LEFT) controllerFocus = Math.max(controllerFocus < 3 ? 0 : 3, controllerFocus - 1);
            else if (key == KeyEvent.KEYCODE_DPAD_RIGHT) controllerFocus = Math.min(controllerFocus < 3 ? 2 : 4, controllerFocus + 1);
        }
        if (activate && e.getAction() == KeyEvent.ACTION_UP) {
            if (controllerFocus < 3) launch(controllerFocus);
            else setMode(controllerFocus == 3 ? "direct" : "bnet");
        }
        View focused = controllerFocus < 3 ? tiles[controllerFocus] : controllerFocus == 3 ? direct : bnet;
        focused.requestFocus(); redrawFocus();
        return true;
    }

    private static final class ShellResult {
        final int code; final String text;
        ShellResult(int code, String text) { this.code = code; this.text = text; }
    }
    private static ShellResult shell(String command, int timeout) {
        Process process = null;
        try {
            process = new ProcessBuilder("su", "--mount-master", "-c", command).redirectErrorStream(true).start();
            if (!process.waitFor(timeout, TimeUnit.SECONDS)) {
                process.destroyForcibly(); return new ShellResult(-1, "");
            }
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream in = process.getInputStream()) {
                byte[] b = new byte[1024]; int count;
                while (output.size() < 4096 && (count = in.read(b)) != -1) output.write(b, 0, count);
            }
            return new ShellResult(process.exitValue(), output.toString("UTF-8"));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt(); return new ShellResult(-1, "");
        } catch (IOException e) { return new ShellResult(-1, ""); }
        finally {
            if (process != null) {
                try { process.getInputStream().close(); } catch (IOException ignored) { }
                try { process.getErrorStream().close(); } catch (IOException ignored) { }
                try { process.getOutputStream().close(); } catch (IOException ignored) { }
                process.destroy();
            }
        }
    }

    /** Inset metal edge, not a floating Material card. Focus is a gold frame, never color alone. */
    private final class MenuFrame extends Drawable {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final boolean control;
        private final int controlIndex;
        MenuFrame(boolean control) { this(control, -1); }
        MenuFrame(boolean control, int controlIndex) { this.control = control; this.controlIndex = controlIndex; }
        @Override public boolean isStateful() { return control; }
        @Override protected boolean onStateChange(int[] state) { invalidateSelf(); return true; }
        @Override public void draw(Canvas canvas) {
            Rect r = getBounds(); boolean selected = false, focus = false, pressed = false, enabled = false;
            for (int state : getState()) {
                selected |= state == android.R.attr.state_selected; focus |= state == android.R.attr.state_focused;
                pressed |= state == android.R.attr.state_pressed; enabled |= state == android.R.attr.state_enabled;
            }
            if (controllerNavigating && controlIndex >= 0) focus = controllerFocus == controlIndex;
            int fill = control ? selected ? RED : PANEL : INK;
            paint.setShader(null); paint.setStyle(Paint.Style.FILL); paint.setColor(fill); canvas.drawRect(r, paint);
            // Fine horizontal grain stays quiet beneath the artwork.
            if (!control) {
                paint.setColor(0x05ffffff);
                for (int y = r.top; y < r.bottom; y += dp(4)) canvas.drawLine(r.left, y, r.right, y, paint);
            }
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(focus ? 2 : 1));
            paint.setColor(focus ? GOLD : control ? 0xff645238 : 0xff332f26);
            canvas.drawRect(r.left + dp(2), r.top + dp(2), r.right - dp(2), r.bottom - dp(2), paint);
            paint.setStyle(Paint.Style.FILL);
            if (pressed || control && !enabled) { paint.setColor(0x60000000); canvas.drawRect(r, paint); }
        }
        @Override public void setAlpha(int alpha) { }
        @Override public void setColorFilter(ColorFilter filter) { }
        @Override public int getOpacity() { return PixelFormat.OPAQUE; }
    }
    private final class GameTile extends View {
        private final int index;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
        private final Bitmap artwork;
        private final RectF bounds = new RectF();
        private final Rect source = new Rect();
        GameTile(int index) {
            super(LaunchActivity.this); this.index = index;
            Bitmap loaded = null;
            try (InputStream in = getAssets().open(flavors[index] + ".jpg")) { loaded = BitmapFactory.decodeStream(in); }
            catch (IOException ignored) { }
            artwork = loaded;
        }
        @Override protected void drawableStateChanged() { super.drawableStateChanged(); invalidate(); }
        @Override protected void onDraw(Canvas c) {
            super.onDraw(c);
            float w = getWidth(), h = getHeight(), inset = dp(4);
            paint.setShader(null); paint.setStyle(Paint.Style.FILL); paint.setColor(PANEL); c.drawRect(0, 0, w, h, paint);
            bounds.set(inset, inset, w - inset, h - inset);
            if (artwork != null) {
                float scale = Math.max(bounds.width() / artwork.getWidth(), bounds.height() / artwork.getHeight());
                int sw = Math.min(artwork.getWidth(), Math.round(bounds.width() / scale));
                int sh = Math.min(artwork.getHeight(), Math.round(bounds.height() / scale));
                source.set((artwork.getWidth() - sw) / 2, 0, (artwork.getWidth() + sw) / 2, sh);
                c.drawBitmap(artwork, source, bounds, paint);
            }
            paint.setShader(new LinearGradient(0, h * .40f, 0, h, new int[]{0x00101013, 0xe0101013, 0xff101013}, new float[]{0, .64f, 1}, Shader.TileMode.CLAMP));
            c.drawRect(bounds, paint); paint.setShader(null);
            if (!isEnabled()) { paint.setColor(0x70000000); c.drawRect(bounds, paint); }
            paint.setTextAlign(Paint.Align.CENTER); paint.setTypeface(heading); paint.setTextSize(dp(27)); paint.setColor(CREAM);
            paint.setShadowLayer(dp(2), 0, dp(1), Color.BLACK); c.drawText(titles[index], w / 2, h - dp(76), paint); paint.clearShadowLayer();
            paint.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL)); paint.setTextSize(dp(9)); paint.setColor(GOLD);
            c.drawText(subtitles[index], w / 2, h - dp(57), paint);
            float left = dp(24), top = h - dp(44), right = w - dp(24), bottom = h - dp(12);
            paint.setColor(isPressed() ? 0xffa02c31 : RED); c.drawRect(left, top, right, bottom, paint);
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(1)); paint.setColor(0xff84633a); c.drawRect(left, top, right, bottom, paint);
            paint.setStyle(Paint.Style.FILL); paint.setTypeface(heading); paint.setTextSize(dp(14)); paint.setColor(CREAM);
            c.drawText("running".equals(phase) ? "Return to game" : "Enter World", w / 2, bottom - dp(10), paint);
            boolean focused = controllerNavigating ? controllerFocus == index : hasFocus();
            paint.setStyle(Paint.Style.STROKE); paint.setStrokeWidth(dp(focused ? 2 : 1));
            paint.setColor(focused ? GOLD : 0xff5b4932); c.drawRect(inset / 2, inset / 2, w - inset / 2, h - inset / 2, paint);
            paint.setStyle(Paint.Style.FILL); paint.setColor(focused ? GOLD : 0xff78613e);
            float d = dp(8);
            for (int corner = 0; corner < 4; corner++) {
                float x = (corner & 1) == 0 ? 0 : w, y = corner < 2 ? 0 : h;
                Path p = new Path(); p.moveTo(x, y); p.lineTo(x + ((corner & 1) == 0 ? d : -d), y);
                p.lineTo(x, y + (corner < 2 ? d : -d)); p.close(); c.drawPath(p, paint);
            }
        }
    }
}
