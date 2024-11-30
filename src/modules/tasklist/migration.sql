ALTER TABLE tasklist
    DROP CONSTRAINT fk_tasklist_users;

ALTER TABLE tasklist
    ADD CONSTRAINT fk_tasklist_users
    FOREIGN KEY (userid)
    REFERENCES user_profiles (profileid)
    ON DELETE CASCADE
    ON UPDATE CASCADE
NOT VALID;
ALTER TABLE tasklist
    ADD COLUMN duration INTEGER;
