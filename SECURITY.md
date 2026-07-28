# Security Policy

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report them privately using
[GitHub's private vulnerability reporting](https://github.com/mattgotteiner/samples/security/advisories/new).

Please include as much of the following as you can, to help us triage quickly:

- the type of issue (for example: credential exposure, injection, privilege escalation),
- the sample and file paths involved,
- the steps required to reproduce it,
- proof-of-concept code, if you have it,
- the impact, including how an attacker might exploit it.

You should receive an initial response within 5 business days.

If the vulnerability is in an underlying Microsoft product or service rather than
in this repository's sample code, please report it to the
[Microsoft Security Response Center](https://msrc.microsoft.com/create-report).

## Scope

This repository contains sample code intended for learning and evaluation. It is
not a supported product and is not hardened for production use.

In particular, note the following about the samples here:

- They provision real Azure resources that cost money. Run `azd down` when done.
- They may create Microsoft Entra application registrations and client secrets.
  Treat any generated secret as sensitive, keep it out of source control, and
  delete the application registration when you are finished.
- They use user-delegated authentication. Data returned reflects the permissions
  of the signed-in user; do not test with an account that has access to data you
  are not authorized to view.

## Preferred languages

We prefer all communications to be in English.
