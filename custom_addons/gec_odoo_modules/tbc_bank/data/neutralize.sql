-- point every TBC connection at the test host and drop its credentials and token
UPDATE tbc_connection
   SET environment = 'test',
       api_host = NULL,
       client_secret = NULL,
       access_token = NULL,
       token_expiry = NULL,
       state = 'blocked';
