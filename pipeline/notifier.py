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

    onset_line = ""
    if metrics.get("domain_median_onset_date"):
        onset_line = f"\nDomain Median Onset (P50)       : {metrics['domain_median_onset_date']} (DOY {metrics['domain_median_onset_doy']}) [Spread: {metrics.get('onset_p10_date')} - {metrics.get('onset_p90_date')}]"

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

PHYSICAL DYNAMICAL & ONSET SUMMARY:
--------------------------------------------------------------------------------
Domain Mean Rainfall (Forecast) : {metrics['domain_mean_op_mm']} mm
Domain Mean Rainfall (Hindcasts): {metrics['domain_mean_hist_mm']} mm
Anomaly relative to model climate: {metrics['anomaly_pct']:+.1f}%{onset_line}

CALIBRATED CATEGORY BREAKDOWN ({metrics['active_cells']} Active Pixels):
--------------------------------------------------------------------------------
- Above Normal (AN) : {metrics['above_cells']:4d} pixels ({metrics['above_pct']:5.1f}%) | Mean prob: {metrics['mean_an']}%
- Near Normal  (NN) : {metrics['normal_cells']:4d} pixels ({metrics['normal_pct']:5.1f}%) | Mean prob: {metrics['mean_nn']}%
- Below Normal (BN) : {metrics['below_cells']:4d} pixels ({metrics['below_pct']:5.1f}%) | Mean prob: {metrics['mean_bn']}%
- No Dominant Tercile: {metrics['neutral_cells']:4d} pixels ({metrics['neutral_pct']:5.1f}%) | Prob < 40%

ATTACHED MAP FIGURES:
--------------------------------------------------------------------------------
1. Rainfall Terciles Map        : {country}_{season}_{year}_Rainfall_Terciles.png
2. Ensemble Median Onset (P50)  : {country}_{season}_{year}_Median_Onset_P50.png

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

    onset_html_block = ""
    if metrics.get("domain_median_onset_date"):
        onset_html_block = f"""
        <div style="font-size: 13px; color: #f8fafc; margin-top: 8px; line-height: 1.5; border-top: 1px solid #334155; padding-top: 8px;">
          Ensemble Median Onset (P50): <strong style="color: #38bdf8;">{metrics['domain_median_onset_date']}</strong> 
          <span style="color: #cbd5e1; font-size: 12px;">(DOY {metrics['domain_median_onset_doy']} | P10–P90 spread: {metrics.get('onset_p10_date')} – {metrics.get('onset_p90_date')})</span>
        </div>
        """

    # HTML version with high-contrast, inline-styled elements
    html_content = f"""
<!DOCTYPE html>
<html>
<head>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b1329; color: #f8fafc; padding: 20px; }}
    .card {{ background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; max-width: 700px; margin: 0 auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
  </style>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b1329; color: #f8fafc; padding: 20px; margin: 0;">
  <div class="card" style="background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 24px; max-width: 700px; margin: 0 auto; box-shadow: 0 10px 25px rgba(0,0,0,0.5);">
    <span style="display: inline-block; background-color: #0284c7; color: #ffffff; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">Forecast Staged • Action Required</span>
    <h1 style="font-size: 22px; font-weight: 800; margin: 14px 0 4px 0; color: #38bdf8;">{country}: {season} ({year})</h1>
    <div style="font-size: 13px; color: #cbd5e1; margin-bottom: 20px;">Valid Period: <strong style="color: #ffffff;">{target_period} {year}</strong> | Model: <strong style="color: #ffffff;">{model}</strong> (Init: {init_date})</div>

    <div style="background-color: #0f172a; border-left: 4px solid #38bdf8; padding: 14px 16px; border-radius: 6px; margin-bottom: 20px; border: 1px solid #334155;">
      <div style="font-weight: 800; color: #38bdf8; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">Physical Dynamical Signal & Timing</div>
      <div style="font-size: 13px; color: #f8fafc; margin-top: 6px; line-height: 1.5;">
        ECMWF SEAS5 simulates a domain mean rainfall of <strong style="color: #ffffff;">{metrics['domain_mean_op_mm']} mm</strong> vs historical hindcast climate of <strong style="color: #ffffff;">{metrics['domain_mean_hist_mm']} mm</strong> (<strong style="color: #4ade80;">{metrics['anomaly_pct']:+.1f}% anomaly</strong>).
      </div>
      {onset_html_block}
    </div>

    <h3 style="font-size: 14px; font-weight: 700; margin: 20px 0 8px 0; color: #ffffff; text-transform: uppercase; letter-spacing: 0.5px;">Calibrated Category Breakdown ({metrics['active_cells']} Active Pixels)</h3>
    <table style="width: 100%; border-collapse: collapse; margin: 12px 0 20px 0; background-color: #0f172a; border-radius: 8px; overflow: hidden; border: 1px solid #334155;">
      <thead>
        <tr style="background-color: #1e293b; border-bottom: 2px solid #475569;">
          <th style="color: #f8fafc; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 12px 10px; text-align: left;">Category</th>
          <th style="color: #f8fafc; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 12px 10px; text-align: center;">Grid Cells</th>
          <th style="color: #f8fafc; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 12px 10px; text-align: center;">Coverage</th>
          <th style="color: #f8fafc; font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 12px 10px; text-align: right;">Mean Probability</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom: 1px solid #334155; background-color: #1e293b;">
          <td style="color: #ffffff; font-size: 13px; font-weight: 700; padding: 12px 10px; text-align: left;">
            <span style="background-color: #417d21; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span>
            <span style="color: #ffffff;">Above Normal</span>
          </td>
          <td style="color: #ffffff; font-size: 13px; font-weight: 600; padding: 12px 10px; text-align: center;">{metrics['above_cells']}</td>
          <td style="color: #4ade80; font-size: 14px; font-weight: 800; padding: 12px 10px; text-align: center;">{metrics['above_pct']}%</td>
          <td style="color: #ffffff; font-size: 13px; font-weight: 600; padding: 12px 10px; text-align: right;">{metrics['mean_an']}% (max {metrics['max_an']}%)</td>
        </tr>
        <tr style="border-bottom: 1px solid #334155; background-color: #1e293b;">
          <td style="color: #ffffff; font-size: 13px; font-weight: 700; padding: 12px 10px; text-align: left;">
            <span style="background-color: #88fbfe; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span>
            <span style="color: #ffffff;">Near Normal</span>
          </td>
          <td style="color: #ffffff; font-size: 13px; font-weight: 600; padding: 12px 10px; text-align: center;">{metrics['normal_cells']}</td>
          <td style="color: #38bdf8; font-size: 14px; font-weight: 800; padding: 12px 10px; text-align: center;">{metrics['normal_pct']}%</td>
          <td style="color: #ffffff; font-size: 13px; font-weight: 600; padding: 12px 10px; text-align: right;">{metrics['mean_nn']}%</td>
        </tr>
        <tr style="border-bottom: 1px solid #334155; background-color: #1e293b;">
          <td style="color: #ffffff; font-size: 13px; font-weight: 700; padding: 12px 10px; text-align: left;">
            <span style="background-color: #e1351e; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span>
            <span style="color: #ffffff;">Below Normal</span>
          </td>
          <td style="color: #ffffff; font-size: 13px; font-weight: 600; padding: 12px 10px; text-align: center;">{metrics['below_cells']}</td>
          <td style="color: #f87171; font-size: 14px; font-weight: 800; padding: 12px 10px; text-align: center;">{metrics['below_pct']}%</td>
          <td style="color: #ffffff; font-size: 13px; font-weight: 600; padding: 12px 10px; text-align: right;">{metrics['mean_bn']}%</td>
        </tr>
        <tr style="background-color: #1e293b;">
          <td style="color: #ffffff; font-size: 13px; font-weight: 700; padding: 12px 10px; text-align: left;">
            <span style="background-color: #ffffff; border: 1px solid #94a3b8; width: 14px; height: 14px; border-radius: 3px; display: inline-block; vertical-align: middle; margin-right: 6px;"></span>
            <span style="color: #ffffff;">No Dominant Tercile (&lt;40%)</span>
          </td>
          <td style="color: #ffffff; font-size: 13px; font-weight: 600; padding: 12px 10px; text-align: center;">{metrics['neutral_cells']}</td>
          <td style="color: #e2e8f0; font-size: 14px; font-weight: 800; padding: 12px 10px; text-align: center;">{metrics['neutral_pct']}%</td>
          <td style="color: #94a3b8; font-size: 13px; font-weight: 500; padding: 12px 10px; text-align: right;">Neutral Climatology</td>
        </tr>
      </tbody>
    </table>

    <!-- Dual Map Previews Section -->
    <div style="margin: 24px 0 20px 0;">
      <h3 style="font-size: 14px; font-weight: 700; color: #ffffff; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.5px;">
        Operational Forecast Map Figures
      </h3>
      <table style="width: 100%; border-collapse: collapse;">
        <tr>
          <td style="width: 48%; padding: 10px; vertical-align: top; background-color: #0f172a; border-radius: 8px; border: 1px solid #334155; text-align: center;">
            <div style="font-size: 12px; font-weight: 800; color: #38bdf8; margin-bottom: 8px;">🌧️ 1. Rainfall Terciles</div>
            <img src="cid:preview_tercile_map" style="width: 100%; max-width: 290px; border-radius: 6px; display: block; margin: 0 auto; border: 1px solid #334155;" alt="Rainfall Terciles Map" />
            <div style="font-size: 11px; color: #cbd5e1; margin-top: 8px; font-weight: 600;">Calibrated Tercile Probabilities</div>
          </td>
          <td style="width: 4%;"></td>
          <td style="width: 48%; padding: 10px; vertical-align: top; background-color: #0f172a; border-radius: 8px; border: 1px solid #334155; text-align: center;">
            <div style="font-size: 12px; font-weight: 800; color: #4ade80; margin-bottom: 8px;">📅 2. Median Onset (P50)</div>
            <img src="cid:preview_onset_map" style="width: 100%; max-width: 290px; border-radius: 6px; display: block; margin: 0 auto; border: 1px solid #334155;" alt="Ensemble Median Onset Map" />
            <div style="font-size: 11px; color: #cbd5e1; margin-top: 8px; font-weight: 600;">Ensemble Median DOY & Calendar Date</div>
          </td>
        </tr>
      </table>
    </div>

    <div style="text-align: center; margin: 24px 0 16px 0;">
      <a href="{approve_api_link}" style="display: inline-block; background-color: #10b981; color: #ffffff; text-decoration: none; padding: 14px 28px; border-radius: 8px; font-weight: 800; font-size: 14px; text-align: center; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);">✓ Approve & Publish to Dashboard</a>
    </div>

    <div style="margin-top: 16px;">
      <div style="font-size: 12px; color: #cbd5e1; font-weight: 600;">Or approve via terminal:</div>
      <div style="background-color: #020617; border: 1px solid #334155; padding: 12px 14px; border-radius: 6px; font-family: Consolas, monospace; font-size: 12px; color: #38bdf8; word-break: break-all; margin-top: 6px;">{approve_cli_cmd}</div>
    </div>

    <div style="font-size: 11px; color: #64748b; margin-top: 24px; border-top: 1px solid #334155; padding-top: 12px;">
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

        # 1. Attach Rainfall Tercile Preview Image
        tercile_png = stage_dir / "preview_tercile_map.png"
        if tercile_png.exists():
            with open(tercile_png, "rb") as img_f:
                img_data = img_f.read()
                img_part = MIMEImage(img_data)
                img_part.add_header("Content-ID", "<preview_tercile_map>")
                clean_name = f"{country}_{season}_{year}_Rainfall_Terciles.png".replace(" ", "_").replace(":", "_").replace("(", "").replace(")", "")
                img_part.add_header("Content-Disposition", "attachment", filename=clean_name)
                msg.attach(img_part)

        # 2. Attach Median Onset Preview Image
        onset_png = stage_dir / "preview_onset_median_map.png"
        if onset_png.exists():
            with open(onset_png, "rb") as img_f:
                img_data = img_f.read()
                img_part = MIMEImage(img_data)
                img_part.add_header("Content-ID", "<preview_onset_map>")
                clean_onset_name = f"{country}_{season}_{year}_Median_Onset_P50.png".replace(" ", "_").replace(":", "_").replace("(", "").replace(")", "")
                img_part.add_header("Content-Disposition", "attachment", filename=clean_onset_name)
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
