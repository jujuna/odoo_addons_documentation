-- Invalidate copied ID-card signing sessions, including ones still within their TTL.
-- Keep completed signatures and their certificate/audit metadata.
UPDATE sign_request_item
   SET geoeid_token = NULL,
       geoeid_token_expiry = NULL;
