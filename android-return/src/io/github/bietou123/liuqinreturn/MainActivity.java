package io.github.bietou123.liuqinreturn;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private TextView status;
    private Button checkButton;
    private Button returnButton;
    private boolean busy;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setGravity(Gravity.CENTER_HORIZONTAL);
        int padding = Math.round(24 * getResources().getDisplayMetrics().density);
        content.setPadding(padding, padding, padding, padding);
        TextView heading = new TextView(this);
        heading.setText("返回 Ubuntu");
        heading.setTextSize(30);
        heading.setTextColor(Color.rgb(233, 84, 32));
        content.addView(heading);
        TextView explanation = new TextView(this);
        explanation.setText("小米 Pad 6 Pro 双系统\n在平板内切换，不需要电脑。\n保存工作后再切换；不清数据、不改分区、不改槽位。\n需要 KernelSU 已授予本应用超级用户权限。");
        explanation.setTextSize(18);
        explanation.setPadding(0, padding, 0, padding);
        content.addView(explanation);
        checkButton = new Button(this);
        checkButton.setText("检查返程环境");
        checkButton.setOnClickListener(view -> execute(false));
        content.addView(checkButton);
        returnButton = new Button(this);
        returnButton.setText("返回 Ubuntu");
        returnButton.setOnClickListener(view -> new AlertDialog.Builder(this)
                .setTitle("确认返回 Ubuntu")
                .setMessage("请先保存 Android 中的工作。将校验镜像、写回 boot_a 并重启进入 Ubuntu。继续？")
                .setNegativeButton("取消", null)
                .setPositiveButton("保存好了，返回", (dialog, selection) -> execute(true))
                .show());
        content.addView(returnButton);
        status = new TextView(this);
        status.setText("先点检查。若提示未授权，请打开 KernelSU → 超级用户，允许“返回 Ubuntu”。");
        status.setTextSize(16);
        status.setPadding(0, padding, 0, 0);
        content.addView(status);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(content);
        setContentView(scroll);
    }

    private void execute(boolean switching) {
        if (busy) {
            return;
        }
        busy = true;
        checkButton.setEnabled(false);
        returnButton.setEnabled(false);
        status.setText(switching ? "正在安全检查并返回 Ubuntu，请勿断电。" : "正在核验 Root、模块、镜像、电量与 OTA 防护……");
        worker.execute(() -> {
            String message;
            try {
                String action = switching ? "return" : "check";
                Process process = new ProcessBuilder("/system/bin/su", "-c",
                        "exec /system/bin/sh /data/adb/modules/liuqin_dual_return/action.sh " + action)
                        .redirectErrorStream(true).start();
                StringBuilder output = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        if (output.length() < 65536) {
                            output.append(line).append('\n');
                        }
                    }
                }
                int exitCode = process.waitFor();
                message = (exitCode == 0 ? "检查通过\n" : "已停止（没有绕过检查）\n") + output;
                if (exitCode != 0) {
                    message += "\n如果是 Root 权限问题，请在 KernelSU 的超级用户页面允许本应用。";
                }
            } catch (Exception error) {
                message = "未能执行返程检查：" + error.getMessage() + "\n请确认 KernelSU 和返程模块仍启用。";
            }
            String result = message;
            runOnUiThread(() -> {
                if (!isFinishing() && !isDestroyed()) {
                    status.setText(result);
                    busy = false;
                    checkButton.setEnabled(true);
                    returnButton.setEnabled(true);
                }
            });
        });
    }

    @Override
    protected void onDestroy() {
        worker.shutdown();
        super.onDestroy();
    }
}
