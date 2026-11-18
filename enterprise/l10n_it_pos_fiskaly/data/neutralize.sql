-- disable l10n_it_pos_fiskaly (fiskaly SIGN IT)
UPDATE res_company
   SET l10n_it_fiskaly_test_mode = true,
       l10n_it_fiskaly_api_key = 'dummy_value',
       l10n_it_fiskaly_api_secret = 'dummy_value',
       l10n_it_fiskaly_access_token = 'dummy_value',
       l10n_it_fiskaly_organization_id = 'dummy_value',
       l10n_it_fiskaly_subject_id = 'dummy_value',
       l10n_it_fiskaly_subject_api_key = 'dummy_value',
       l10n_it_fiskaly_subject_api_secret = 'dummy_value',
       l10n_it_fiskaly_subject_access_token = 'dummy_value',
       l10n_it_fiskaly_taxpayer_id = 'dummy_value',
       l10n_it_fiskaly_location_id = 'dummy_value',
       l10n_it_fisconline_tax_id = 'dummy_value',
       l10n_it_fisconline_pin = 'dummy_value',
       l10n_it_fisconline_password = 'dummy_value'
 WHERE l10n_it_fiskaly_api_key IS NOT NULL
    OR l10n_it_fiskaly_subject_api_key IS NOT NULL;

UPDATE pos_config
   SET l10n_it_fiskaly_system_id = 'dummy_value'
 WHERE l10n_it_fiskaly_system_id IS NOT NULL;
