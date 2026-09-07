---
name: lets-encrypt-dns01-octodns-renewal
description: Use when issuing or renewing a Let's Encrypt certificate through getssl DNS-01 hooks backed by an authorized OctoDNS repository.
---

# Let's Encrypt DNS-01 renewal through OctoDNS

Use this only for a certificate whose DNS-01 automation is already configured to use the
team-maintained `getssl` and OctoDNS integration. This Skill explains the operational
boundary; it does not grant DNS, repository, CA-account, or private-key access.

## Decide whether you may proceed

Before running a renewal, establish all of the following without printing secret values:

- You have explicit authorization to renew this certificate and apply its temporary DNS
  challenge records.
- You can access the configured `getssl` checkout and its existing local configuration for
  the requested certificate name.
- You can access the OctoDNS checkout named by that configuration, including the correct
  target zone and its supported environment.
- The DNS-provider credentials required by OctoDNS are already available through the
  approved local secret mechanism, and the OctoDNS environment can run a dry-run.
- The installed DNS hooks use the strict OctoDNS plan gate. For creation it must accept only
  the expected ACME TXT record; for removal it must accept only its expected deletion.

If any condition is missing, stop before invoking `getssl`. Report the missing capability
or authorization to the responsible certificate/DNS operator. Do not request, paste, log,
or store credentials in a repository, terminal transcript, ticket, or Skill.

## Safe DNS-01 sequence

1. Confirm the certificate name, all SANs, the correct authoritative DNS zone, and the
   existing `getssl` configuration. A wildcard name uses DNS-01 but does not itself prove
   ownership of a zone or permission to change it.
2. Run the configured renewal through the existing `getssl` entry point. Let its configured
   DNS add hook create `_acme-challenge` TXT data through OctoDNS; do not hand-edit a zone or
   substitute an unrelated DNS provider while that hook is active.
3. Inspect the OctoDNS dry-run. It must contain only the expected challenge-record action:
   exactly one TXT creation during setup, then exactly one TXT deletion during cleanup. Any
   extra create, update, delete, wrong record name, wrong token, or unparseable plan is a
   stop condition.
4. A pre-existing correct TXT value may be treated as a creation no-op only when the local
   mutator explicitly reported that exact value already exists and the installed gate has
   explicit creation-no-op support. Never use that exception for cleanup.
5. Wait for the configured authoritative-DNS verification and let the ACME client complete
   issuance. Issuance is not deployment: do not claim an application, cluster, proxy, or
   service has installed or reloaded the new certificate unless that separate action is
   evidenced.
6. Verify the certificate dates, requested names, and certificate/private-key correspondence.
   Confirm that the ACME TXT record was removed after completion.

## Artifact handling

Keep the original full-chain certificate and matching private-key files as the source
artifacts. Send a private key only through the approved secure channel. Do not combine the
private key with certificate text in a convenience file, commit either artifact, or place it
in shared storage without explicit approved protection.

## Source of truth and escalation

The executable behavior belongs to the maintained `getssl` DNS hooks and the authorized
OctoDNS repository, not this Skill. If their configuration, plan format, or guardrail
behavior differs from this procedure, stop and have the integration owner review it before
renewing.
