-- Block copied Basis Bank connections and discard cached banking sessions.
-- Keep api_host: it is required. Keep login_name for diagnostics.
UPDATE basisbank_connection
   SET password = NULL,
       ticket_id = NULL,
       ticket_expiry = NULL,
       state = 'blocked';
