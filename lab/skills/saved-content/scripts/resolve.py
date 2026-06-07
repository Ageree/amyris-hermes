#!/usr/bin/env python3
"""Resolve a shared URL into text + media files on disk for the agent to analyze."""
import argparse, json, os, re, subprocess, sys
import requests

def classify(url):
    host = re.sub(r"^www\.", "", re.match(r"https?://([^/]+)", url).group(1).lower())
    if "instagram.com" in host: return "instagram"
    if "tiktok.com" in host: return "tiktok"
    if host in ("x.com", "twitter.com", "mobile.twitter.com"): return "x"
    if "youtube.com" in host or host == "youtu.be": return "youtube"
    return "article"
