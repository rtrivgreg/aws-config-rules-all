#!/usr/bin/env python3
"""
bindingsNG.py — organizational RULE_BINDING writer, plus an explicit NIAID
baseline refresh path.

Default mode writes only RULE_BINDING items so cpgNG can overlay group-specific
parameter values on the NIAID baseline. It does not fabricate packs or deploy
Config resources.

--update mode reconciles NIAID RULE_PROFILE and PARAMETER_DEF rows from the
AWS managed-rule CloudFormation template. It never writes GROUP# bindings.
"""
