#!/usr/bin/env bash
set -euo pipefail

[ -n "${STATIC_S3_BUCKET:-}" ] || exit 0

loc="static"
args=(
  --set STORAGES.staticfiles.BACKEND "portal_storage.PortalStaticS3Storage"
  --set STORAGES.staticfiles.OPTIONS.bucket_name "$STATIC_S3_BUCKET"
  --set STORAGES.staticfiles.OPTIONS.region_name "${AWS_REGION:-us-east-1}"
  --set STORAGES.staticfiles.OPTIONS.location "$loc"
  --set STORAGES.staticfiles.OPTIONS.querystring_auth false
  --set STORAGES.default.BACKEND "storages.backends.s3.S3Storage"
  --set STORAGES.default.OPTIONS.bucket_name "$STATIC_S3_BUCKET"
  --set STORAGES.default.OPTIONS.region_name "${AWS_REGION:-us-east-1}"
  --set STORAGES.default.OPTIONS.location "media"
  --set STORAGES.default.OPTIONS.querystring_auth false
)
if [ -n "${STATIC_CLOUDFRONT_DOMAIN:-}" ]; then
  args+=( --set STORAGES.staticfiles.OPTIONS.custom_domain "$STATIC_CLOUDFRONT_DOMAIN" )
  args+=( --set STATIC_URL "https://${STATIC_CLOUDFRONT_DOMAIN}/${loc}/" )
  args+=( --set STORAGES.default.OPTIONS.custom_domain "$STATIC_CLOUDFRONT_DOMAIN" )
  args+=( --set MEDIA_URL "https://${STATIC_CLOUDFRONT_DOMAIN}/media/" )
fi
tethys settings "${args[@]}"
echo "portal storages: bucket=$STATIC_S3_BUCKET domain=${STATIC_CLOUDFRONT_DOMAIN:-none}"
