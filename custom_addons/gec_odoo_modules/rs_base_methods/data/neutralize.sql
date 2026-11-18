-- Pending SMS challenges can obtain a fresh access token without the saved login.
-- Discard these transient authentication attempts; pin_token is NOT NULL.
DELETE FROM rs_auth_pin_wizard;

-- Company-dependent fields fall back to ir.default when their JSONB value
-- is empty. Remove credential defaults for every company/user first.
DELETE FROM ir_default
 WHERE field_id IN (
       SELECT id
         FROM ir_model_fields
        WHERE model = 'res.users.settings'
          AND name IN (
              'rs_username', 'rs_password', 'rs_user_id', 'rs_access_token',
              'rs_token_expiry', 'rs_device_code', 'rs_device_paired_on'
          )
 );

-- Clear all companies' rs.ge SOAP/REST credentials, sessions and device pairing.
-- Covers every integration reading credentials through rs_base_methods.
-- Keep rs_un_id and rs_is_responsible: taxpayer identity and responsibility.
UPDATE res_users_settings
   SET rs_username = NULL,
       rs_password = NULL,
       rs_user_id = NULL,
       rs_access_token = NULL,
       rs_token_expiry = NULL,
       rs_device_code = NULL,
       rs_device_paired_on = NULL;
