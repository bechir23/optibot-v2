-- Seed 41 action templates from OptiBot v1 action_space.py
-- These become the initial tool catalog, loadable per-mutuelle

INSERT INTO action_templates (id, phase, template, description) VALUES
-- Phase 0: Detection
('P0_DETECT_IVR', 'detection', 'Naviguer dans le menu telephonique', 'IVR menu detected'),
('P0_DETECT_VOICEMAIL', 'detection', 'Messagerie vocale detectee', 'Voicemail detected'),
('P0_DETECT_HUMAN', 'detection', 'Un humain a repondu', 'Human agent detected'),

-- Phase 1: IVR Navigation
('P1_PRESS_DIGIT', 'ivr', 'Appuyer sur la touche {digit}', 'Press DTMF digit'),
('P1_WAIT_MENU', 'ivr', 'Ecouter les options du menu', 'Wait for menu options'),
('P1_STUCK', 'ivr', 'Impossible de naviguer dans le menu', 'IVR navigation failed'),
('P1_RETRY', 'ivr', 'Reessayer avec un chemin different', 'Retry IVR with different path'),

-- Phase 2: Hold
('P2_HOLD_START', 'hold', 'Musique d attente detectee', 'Hold music started'),
('P2_HOLD_END', 'hold', 'L agent est de retour', 'Human returned from hold'),
('P2_HOLD_TIMEOUT', 'hold', 'Delai d attente depasse', 'Hold timeout exceeded'),

-- Phase 3A: Identification
('P3_GIVE_NAME', 'identify', 'Le dossier est au nom de {patient_name}.', 'Give patient name'),
('P3_GIVE_DOB', 'identify', 'La date de naissance est le {patient_dob}.', 'Give date of birth'),
('P3_GIVE_NIR', 'identify', 'Le numero de securite sociale est {nir}.', 'Give NIR'),
('P3_GIVE_REF', 'identify', 'La reference du bordereau est {bordereau_ref}.', 'Give bordereau reference'),
('P3_GIVE_MONTANT', 'identify', 'Le montant est de {montant} euros.', 'Give amount'),

-- Phase 3B: Enquiry
('P3_ASK_STATUS', 'enquire', 'Pouvez-vous me dire ou en est le remboursement pour ce dossier ?', 'Ask reimbursement status'),
('P3_ASK_TIMELINE', 'enquire', 'Avez-vous une estimation de la date de traitement ?', 'Ask processing timeline'),
('P3_ASK_REMAINING', 'enquire', 'Quel est le reste a charge ?', 'Ask remaining amount'),
('P3_ASK_REFERENCE', 'enquire', 'Pourriez-vous me donner un numero de reference ?', 'Ask reference number'),
('P3_ASK_MISSING', 'enquire', 'Y a-t-il des pieces manquantes ?', 'Ask missing documents'),
('P3_ASK_REASON', 'enquire', 'Pour quelle raison le dossier est-il en attente ?', 'Ask reason for delay'),
('P3_ASK_CONTACT', 'enquire', 'Quel est le meilleur moyen de vous recontacter ?', 'Ask callback method'),

-- Phase 3C: Acknowledgement
('P3_ACK', 'ack', 'D accord, je note.', 'Simple acknowledgement'),
('P3_ACK_WAIT', 'ack', 'D accord, je patiente.', 'Acknowledge and wait'),
('P3_ACK_REPEAT', 'ack', 'Pouvez-vous repeter s il vous plait ?', 'Ask to repeat'),
('P3_ACK_CONFIRM', 'ack', 'Si je comprends bien, {summary}. C est correct ?', 'Confirm understanding'),
('P3_SILENCE', 'ack', 'Allo ? Vous etes toujours en ligne ?', 'Break silence'),

-- Phase 3D: React
('P3_REACT_POSITIVE', 'react', 'Tres bien, merci pour cette information.', 'Positive reaction'),
('P3_REACT_NEGATIVE', 'react', 'Je comprends. Y a-t-il une demarche a suivre ?', 'React to bad news'),
('P3_REACT_CLARIFY', 'react', 'Pourriez-vous preciser ce point ?', 'Ask clarification'),

-- Phase 4: Close
('P4_CLOSE_SUCCESS', 'close', 'Merci beaucoup pour votre aide. Bonne journee !', 'Close call successfully'),
('P4_CLOSE_CALLBACK', 'close', 'D accord, je rappellerai. Merci. Bonne journee.', 'Close with callback plan'),
('P4_CLOSE_ESCALATE', 'close', 'Je vais verifier avec l opticien et vous rappeler.', 'Escalate to human'),
('P4_CLOSE_FAILED', 'close', 'Je n ai pas pu obtenir l information. Je rappellerai.', 'Close without resolution'),

-- Transfer
('P3_TRANSFER', 'transfer', 'Pourriez-vous me transferer vers le {target_service} ?', 'Request transfer'),

-- Filler (natural turn-taking)
('FILLER_THINKING', 'filler', 'Un instant...', 'Thinking filler'),
('FILLER_CHECKING', 'filler', 'Je verifie...', 'Checking filler'),
('FILLER_NOTING', 'filler', 'Je note...', 'Noting information'),

-- Special
('GREETING', 'greeting', 'Bonjour, je vous appelle de la part de l opticien concernant un dossier de remboursement optique.', 'Opening greeting'),
('GOODBYE', 'goodbye', 'Merci et bonne journee.', 'Goodbye')

ON CONFLICT (id) DO NOTHING;
