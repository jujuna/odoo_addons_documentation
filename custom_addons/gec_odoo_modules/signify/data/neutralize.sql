-- Signify OAuth: remove the partner credentials and every stored token.
DELETE FROM ir_config_parameter WHERE key IN ('signify.client_id', 'signify.client_secret');
UPDATE signify_connection SET access_token = NULL, refresh_token = NULL, expiry = NULL;
