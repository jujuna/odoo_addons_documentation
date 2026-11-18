DELETE FROM platform_order_wolt_token;
UPDATE platform_order_entity
   SET wolt_oauth_state = NULL;
UPDATE platform_order_provider
   SET wolt_client_secret = NULL,
       wolt_webhook_secret = NULL;
