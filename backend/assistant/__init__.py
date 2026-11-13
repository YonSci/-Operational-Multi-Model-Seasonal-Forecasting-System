"""Forecast assistant: evidence records, explanations and run comparisons.

Every explanation is built in three steps:
  1. evidence.py computes a structured evidence record from the platform's own data (values, dates, chances, skill,
     sources and caveats), so the numbers never come from a language model;
  2. narrate.py writes the explanation: a template always, and Claude when ANTHROPIC_API_KEY is set;
  3. checks.py verifies that every number in Claude's text appears in the evidence, and falls back to the template
     when one does not.
"""
