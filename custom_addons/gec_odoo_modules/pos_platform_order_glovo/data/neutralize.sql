-- Remove the token used for Glovo API calls and webhook authentication.
UPDATE platform_order_provider
   SET glovo_token = NULL
 WHERE code = 'glovo';

-- Remove the customer data kept in the stored Glovo notifications.
UPDATE glovo_event
   SET payload = NULL;
