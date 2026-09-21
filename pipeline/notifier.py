"""
pipeline/notifier.py
────────────────────
Notification and Email Dispatcher for Operational Forecasting.
Formats an executive digest email with summary metrics, categorical
breakdown tables, attached/embedded preview maps, and one-click/CLI approval.
"""

import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
from typing import Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pipeline.config import STAGING_DIR, BASE_DIR

def send_notification(manifest: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """
    Generate and dispatch notification email for a staged forecast run.
    If SMTP credentials are not configured, saves email_preview.html to the staging folder.
    """
    run_id = manifest["run_id"]
    stage_dir = STAGING_DIR / run_id
    metrics = manifest["metrics"]
    country = manifest["country"].title()
    season = manifest["season_label"]
    year = manifest["forecast_year"]
    init_date = manifest["init_date"]
    target_period = manifest["target_period"]
    model = manifest["model"]
    token = manifest["approval_token"]

    dashboard_url = os.environ.get("DASHBOARD_URL", "http://localhost:5173")
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    approve_api_link = f"{api_url}/api/pipeline/approve?run_id={run_id}&token={token}"
    approve_cli_cmd = f"python scripts/approve_and_publish.py --run-id {run_id}"

    # Plain text version
    text_content = f"""
================================================================================
  OPERATIONAL FORECAST READY FOR REVIEW & APPROVAL
================================================================================
Country       : {country}
Season        : {season} ({year})
Target Period : {target_period} {year}
Model         : {model} (Init: {init_date})
Run ID        : {run_id}
Status        : PENDING HUMAN APPROVAL

PHYSICAL DYNAMICAL SUMMARY:
--------------------------------------------------------------------------------
Domain Mean Rainfall (Forecast) : {metrics['domain_mean_op_mm']} mm
Domain Mean Rainfall (Hindcasts): {metrics['domain_mean_hist_mm']} mm
Anomaly relative to model climate: {metrics['anomaly_pct']:+.1f}%

CALIBRATED CATEGORY BREAKDOWN ({metrics['active_cells']} Active Pixels):
--------------------------------------------------------------------------------
- Above Normal (AN) : {metrics['above_cells']:4d} pixels ({metrics['above_pct']:5.1f}%) | Mean prob: {metrics['mean_an']}%
- Near Normal  (NN) : {metrics['normal_cells']:4d} pixels ({metrics['normal_pct']:5.1f}%) | Mean prob: {metrics['mean_nn']}%
- Below Normal (BN) : {metrics['below_cells']:4d} pixels ({metrics['below_pct']:5.1f}%) | Mean prob: {metrics['mean_bn']}%
- No Dominant Tercile: {metrics['neutral_cells']:4d} pixels ({metrics['neutral_pct']:5.1f}%) | Prob < 40%

APPROVAL INSTRUCTIONS:
--------------------------------------------------------------------------------
To approve and publish these results to the live operational dashboard:

Option 1 (Command Line):
  {approve_cli_cmd}

Option 2 (Direct Approval Link):
  {approve_api_link}

Artifacts Staged:
  {stage_dir}
================================================================================
"""

    # HTML version
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
    .card {{ background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; max-width: 680px; margin: 0 auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    .badge {{ display: inline-block; background-color: #0284c7; color: white; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; text-transform: uppercase; }}
    .title {{ font-size: 20px; font-weight: 800; margin: 12px 0 4px 0; color: #38bdf8; }}
    .subtitle {{ font-size: 13px; color: #94a3b8; margin-bottom: 20px; }}
    .table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 13px; }}
    .table th {{ background-color: #0f172a; text-align: left; padding: 10px; color: #94a3b8; border-bottom: 1px solid #334155; }}
    .table td {{ padding: 10px; border-bottom: 1px solid #334155; }}
    .swatch-an {{ background-color: #417d21; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px; }}
    .swatch-nn {{ background-color: #88fbfe; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px; }}
    .swatch-bn {{ background-color: #e1351e; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px; }}
    .swatch-neu {{ background-color: #ffffff; border: 1px solid #94a3b8; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px; }}
    .btn {{ display: inline-block; background-color: #10b981; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 700; font-size: 14px; margin-top: 16px; text-align: center; }}
    .cmd {{ background-color: #0f172a; border: 1px solid #334155; padding: 10px 14px; border-radius: 6px; font-family: monospace; font-size: 12px; color: #38bdf8; word-break: break-all; margin-top: 8px; }}
    .footer {{ font-size: 11px; color: #64748b; margin-top: 24px; border-top: 1px solid #334155; padding-top: 12px; }}
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">Forecast Staged • Action Required</span>
    <h1 class="title">{country}: {season} ({year})</h1>
    <div class="subtitle">Valid Period: <strong>{target_period} {year}</strong> | Model: <strong>{model}</strong> (Init: {init_date})</div>

    <div style="background-color: rgba(56, 189, 248, 0.1); border-left: 4px solid #38bdf8; padding: 12px; border-radius: 4px; margin-bottom: 20px;">
      <div style="font-weight: 700; color: #38bdf8; font-size: 13px;">Physical Dynamical Signal</div>
      <div style="font-size: 12px; color: #cbd5e1; margin-top: 4px;">
        ECMWF SEAS5 simulates a domain mean of <strong>{metrics['domain_mean_op_mm']} mm</strong> vs historical hindcast climate of <strong>{metrics['domain_mean_hist_mm']} mm</strong> (<strong style="color: #4ade80;">{metrics['anomaly_pct']:+.1f}% anomaly</strong>).
      </div>
    </div>

    <h3 style="font-size: 14px; margin-bottom: 6px; color: #f1f5f9;">Calibrated Category Breakdown ({metrics['active_cells']} Active Pixels)</h3>
    <table class="table">
      <thead>
        <tr>
          <th>Category</th>
          <th>Grid Cells</th>
          <th>Coverage</th>
          <th>Mean Probability</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><span class="swatch-an"></span><strong>Above Normal</strong></td>
          <td>{metrics['above_cells']}</td>
          <td><strong>{metrics['above_pct']}%</strong></td>
          <td>{metrics['mean_an']}% (max {metrics['max_an']}%)</td>
        </tr>
        <tr>
          <td><span class="swatch-nn"></span><strong>Near Normal</strong></td>
          <td>{metrics['normal_cells']}</td>
          <td><strong>{metrics['normal_pct']}%</strong></td>
          <td>{metrics['mean_nn']}%</td>
        </tr>
        <tr>
          <td><span class="swatch-bn"></span><strong>Below Normal</strong></td>
          <td>{metrics['below_cells']}</td>
          <td><strong>{metrics['below_pct']}%</strong></td>
          <td>{metrics['mean_bn']}%</td>
        </tr>
        <tr>
          <td><span class="swatch-neu"></span><strong>No Dominant Tercile (<40%)</strong></td>
          <td>{metrics['neutral_cells']}</td>
          <td><strong>{metrics['neutral_pct']}%</strong></td>
          <td>Neutral Climatology</td>
        </tr>
      </tbody>
    </table>

    <div style="text-align: center; margin: 20px 0;">
      <a href="{approve_api_link}" class="btn">✓ Approve & Publish to Dashboard</a>
    </div>

    <div style="margin-top: 16px;">
      <div style="font-size: 12px; color: #94a3b8; font-weight: 600;">Or approve via terminal:</div>
      <div class="cmd">{approve_cli_cmd}</div>
    </div>

    <div class="footer">
      Run ID: {run_id} • Generated automatically by Operational Seasonal Forecasting System.
    </div>
  </div>
</body>
</html>
"""

    # Always write HTML preview file in the staging directory
    email_preview_file = stage_dir / "email_preview.html"
    with open(email_preview_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n  [Notifier] Rendered email digest to {email_preview_file}")

    # Check SMTP configuration
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user or "forecast@dashboard.org")
    to_email  = os.environ.get("NOTIFICATION_EMAIL")

    if not smtp_host or not to_email:
        print(f"  [Notifier] Notice: SMTP_HOST or NOTIFICATION_EMAIL not set in environment.")
        print(f"             Digest logged to: {email_preview_file}")
        print(text_content)
        return {"status": "LOGGED_LOCAL", "preview_file": str(email_preview_file)}

    if dry_run:
        print(f"  [Notifier] [DRY RUN] Would send email via {smtp_host}:{smtp_port} to {to_email}")
        return {"status": "DRY_RUN_SUCCESS", "to": to_email}

    # Dispatch via SMTP
    try:
        msg = MIMEMultipart("related")
        msg["Subject"] = f"Action Required: Approve {country} {season} {year} Seasonal Forecast"
        msg["From"] = smtp_from
        msg["To"] = to_email

        msg_alternative = MIMEMultipart("alternative")
        msg.attach(msg_alternative)

        msg_alternative.attach(MIMEText(text_content, "plain", "utf-8"))
        msg_alternative.attach(MIMEText(html_content, "html", "utf-8"))

        # Attach preview image if present
        preview_png = stage_dir / "preview_tercile_map.png"
        if preview_png.exists():
            with open(preview_png, "rb") as img_f:
                img_data = img_f.read()
                img_part = MIMEImage(img_data)
                img_part.add_header("Content-Disposition", "attachment", filename=f"{run_id}_preview.png")
                msg.attach(img_part)

        print(f"  [Notifier] Connecting to SMTP server {smtp_host}:{smtp_port}...")
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print(f"  [Notifier] [OK] Notification email successfully sent to {to_email}!")
        return {"status": "SENT", "to": to_email}
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  [Notifier] WARNING: Failed to send email via SMTP ({e}). Digest remains saved locally.")
        return {"status": "FAILED", "error": str(e), "preview_file": str(email_preview_file)}
