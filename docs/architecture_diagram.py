#!/usr/bin/env python3
"""Draws docs/architecture.png and docs/architecture.svg.   python3 docs/architecture_diagram.py"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

matplotlib.rcParams["svg.fonttype"] = "none"
matplotlib.rcParams["font.family"] = "DejaVu Sans"
fig, ax = plt.subplots(figsize=(16, 10.4))
ax.set_xlim(0, 160); ax.set_ylim(0, 104); ax.axis("off")


def box(x0, y0, x1, y1, text="", fc="#ffffff", ec="#334155", lw=1.4, ls="-", fs=8.5, r=1.2, weight="normal", tc="#0f172a"):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=%s" % r,
                                fc=fc, ec=ec, lw=lw, ls=ls, zorder=2))
    if text:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center", fontsize=fs, zorder=5,
                weight=weight, color=tc, linespacing=1.35)


def frame(x0, y0, x1, y1, title, ec, fc="none", ls="-", fs=9.5, tx=None):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=1.6",
                                fc=fc, ec=ec, lw=2, ls=ls, zorder=1))
    ax.text((x0 + 1.5) if tx is None else tx, y1 - 1.4, title, ha="left", va="top", fontsize=fs, color=ec, weight="bold", zorder=5)


def arrow(p, q, label="", color="#334155", ls="-", rad=0.0, lx=0, ly=0, fs=8, both=False):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="<|-|>" if both else "-|>", mutation_scale=13, lw=1.6, color=color,
                                 ls=ls, connectionstyle="arc3,rad=%s" % rad, zorder=4, shrinkA=0, shrinkB=0))
    if label:
        ax.text((p[0] + q[0]) / 2 + lx, (p[1] + q[1]) / 2 + ly, label, fontsize=fs, color=color, ha="center",
                va="center", zorder=6, bbox=dict(fc="white", ec="none", pad=1.2), linespacing=1.25)


ax.text(2, 101.5, "Tram circular route - AWS architecture", fontsize=16, weight="bold", color="#0f172a", va="center")
ax.text(158, 101.5, "Practical project - AWS DevOps Engineer Professional", fontsize=9, color="#475569",
        ha="right", va="center")

# ---- actors (top band) -------------------------------------------------------------------------
box(4, 83, 40, 96, "Guest\nno login\nlive public view", fc="#e0f7fa", fs=9.5, weight="bold")
box(46, 83, 90, 96, "Registered passenger\nlogin, request ride, follow\nWAITING > ON_BOARD > COMPLETED", fc="#e0f7fa", fs=9.5, weight="bold")
box(96, 83, 112, 96, "GitHub\nrepository\ncode, tests,\ndocs", fc="#f1f5f9", fs=8.5)
box(118, 80, 158, 97, "AWS CloudShell: bash deploy.sh\n1  tests  (a failing test stops here)\n2  upload app/ to S3\n3  CloudFormation deploy\n4  reboot instance (new code)",
    fc="#f1f5f9", fs=8.5)
arrow((112, 89.5), (118, 89.5), "git clone", ly=2.6, fs=7.5)

# ---- AWS account ---------------------------------------------------------------------------------
frame(2, 2, 159, 76, "AWS account (Pluralsight sandbox) - one region", "#0f766e", fs=10.5, tx=26)

frame(6, 6, 104, 72, "Default VPC - public subnet", "#2563eb", tx=26)
box(10, 61, 100, 67.5, "Security group: inbound TCP 80 only (no SSH)", fc="#ffedd5", fs=8.8, ec="#c2410c")
frame(10, 9, 100, 58, "EC2 t3.micro - Amazon Linux 2023", "#2563eb", fc="#eff6ff")
frame(14, 13, 96, 51, "systemd service tram.service  (Restart=always, enabled at boot = long-lived worker)", "#475569", ls="--", fs=8.3)
box(18, 17.5, 54, 44,
    "Web server (port 80)\n\nGET /  page, auto refresh 1 s\nGET /api/state  (public)\nPOST /api/register  /api/login\nGET /api/me   POST /api/ride", fs=8.2)
box(58, 17.5, 92, 44,
    "Worker loop (every 0.25 s)\n\nS01..S16, then S01\nstop 3 s - travel 5 s\nboarding FIFO, max 12 passengers\nCOMPLETED at the destination", fs=8.2)
ax.text(55, 15, "app.py: one process, two threads", ha="center", fontsize=7.8, color="#475569", zorder=6, style="italic")

box(110, 62, 130, 72, "S3 artifact bucket\napp/ code files\npublic access blocked", fc="#dcfce7", ec="#15803d", fs=8)
box(134, 62, 156, 72, "CloudFormation\nstack \"tram\"\ncreates all of this", fc="#ccfbf1", ec="#0f766e", fs=8)
box(110, 38, 156, 50, "IAM role = least privilege (checked by a test)\nper table only the actions the code uses\nS3: read app/* only   -   no keys in the code", fc="#fee2e2", ec="#b91c1c", fs=8)

frame(110, 6, 156, 33, "DynamoDB - ALL state lives here", "#7c3aed", fc="#faf5ff")
box(113, 17.5, 132, 27, "State\ntram position,\nphase start time", fc="#ffffff", ec="#7c3aed", fs=7.6)
box(134, 17.5, 153, 27, "Users\nsalted password hash,\nactive_ride, last_ride", fc="#ffffff", ec="#7c3aed", fs=7.6)
box(113, 8, 132, 16, "Sessions\nlogin tokens (TTL)", fc="#ffffff", ec="#7c3aed", fs=7.6)
box(134, 8, 153, 16, "Rides\nWAITING / ON_BOARD /\nCOMPLETED", fc="#ffffff", ec="#7c3aed", fs=7.6)

# ---- flows ---------------------------------------------------------------------------------------
arrow((22, 83), (22, 67.5), "HTTP", lx=4, fs=8)
arrow((80, 83), (80, 67.5), "HTTP + login token", lx=10, fs=8)
arrow((50, 61), (36, 44.2), "")
arrow((60, 61), (75, 44.2), "")
arrow((100, 25), (110, 25), "", color="#7c3aed")
ax.text(105, 29.8, "boto3\nread / write", fontsize=7.3, color="#7c3aed", ha="center", va="center", zorder=6,
        bbox=dict(fc="white", ec="none", pad=1))
arrow((110, 62), (100, 53), "aws s3 sync\nat service start", color="#15803d", lx=-6, ly=3.6, fs=7.5)
arrow((110, 44), (100, 38), "instance\nprofile", color="#b91c1c", lx=0, ly=-4.6, fs=7.5)
arrow((120, 80.2), (120, 72), "upload", color="#15803d", lx=-4.2, fs=7.5)
arrow((148, 80.2), (146, 72), "deploy template.yaml", lx=-12.5, ly=3.5, fs=7.5)
arrow((145, 62), (145, 50.3), "creates", color="#0f766e", ls="--", lx=5.2, fs=7.5)
arrow((147, 62), (147, 33.2), "", color="#0f766e", ls="--")

ax.text(2, 0.2, "Rules (stations, timing, capacity) are 4 constants in app/logic.py. Tests run before every delivery.",
        fontsize=8, color="#475569", va="bottom")
here = os.path.dirname(os.path.abspath(__file__))
fig.savefig(os.path.join(here, "architecture.png"), dpi=150, bbox_inches="tight", facecolor="white")
fig.savefig(os.path.join(here, "architecture.svg"), bbox_inches="tight", facecolor="white")
print("saved architecture.png / architecture.svg")
