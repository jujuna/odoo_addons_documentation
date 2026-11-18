-- block every Bank of Georgia connection: a copied database must never send real transfers
UPDATE bog_connection
   SET client_secret = NULL,
       access_token = NULL,
       token_expiry = NULL,
       state = 'blocked';
