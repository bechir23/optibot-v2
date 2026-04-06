-- Known mutuelle IVR maps and phone numbers
-- Updated as we learn their phone trees from actual calls

INSERT INTO mutuelle_ivr_maps (mutuelle, phone_number, ivr_tree, avg_wait_minutes, best_call_time, notes) VALUES
('Harmonie Mutuelle', '+33980980980', '{
    "welcome": "Pour les remboursements tapez 1. Pour les adhesions tapez 2. Pour modifier vos garanties tapez 3.",
    "path_to_reimbursement": ["1"],
    "path_to_optical": ["1", "3"],
    "notes": "Le menu change apres 18h — seul le repondeur."
}', 8, '10h-12h', 'Plus grande mutuelle de France. Appeler le matin.'),

('MGEN', '+33969369369', '{
    "welcome": "Tapez 1 pour vos remboursements. Tapez 2 pour modifier vos garanties. Tapez 3 pour une question administrative.",
    "path_to_reimbursement": ["1"],
    "notes": "Temps d attente moyen 12 minutes. Fonctionnaires."
}', 12, '14h-16h', 'Mutuelle fonctionnaires. Apres-midi moins charge.'),

('AG2R La Mondiale', '+33969322222', '{
    "welcome": "Pour le suivi de vos remboursements tapez 1. Pour vos cotisations tapez 2.",
    "path_to_reimbursement": ["1"],
    "notes": "Demandent souvent le numero adherent."
}', 10, '10h-12h', 'Demandent numero adherent systematiquement.'),

('Malakoff Humanis', '+33969642424', '{
    "welcome": "Bienvenue chez Malakoff Humanis. Pour vos remboursements sante tapez 1.",
    "path_to_reimbursement": ["1"],
    "notes": "Menu simple, attente variable."
}', 15, '9h-11h', 'Attente longue. Appeler tot.'),

('Almerys', '+33811709010', '{
    "welcome": "Plateforme de tiers payant. Pour le suivi d un dossier tapez 1.",
    "path_to_reimbursement": ["1"],
    "notes": "Plateforme tiers payant, pas une mutuelle directe."
}', 5, '10h-16h', 'Plateforme TP. Reponse rapide.'),

('Viamedis', '+33170959595', '{
    "welcome": "Pour le suivi de vos factures tapez 1. Pour une question technique tapez 2.",
    "path_to_reimbursement": ["1"],
    "notes": "Plateforme TP comme Almerys."
}', 5, '10h-16h', 'Concurrence Almerys. Rapide.')

ON CONFLICT (mutuelle) DO UPDATE SET
    ivr_tree = EXCLUDED.ivr_tree,
    avg_wait_minutes = EXCLUDED.avg_wait_minutes,
    updated_at = NOW();
