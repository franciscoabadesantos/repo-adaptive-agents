#!/usr/bin/env bash
curl -H "Authorization: Bearer ${CLOUDFLARE_ACCOUNT_TOKEN}" https://api.cloudflare.com/client/v4/zones
