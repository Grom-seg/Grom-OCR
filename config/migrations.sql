-- Criação da tabela de análises para registro e aprendizado incremental
CREATE TABLE IF NOT EXISTS analises (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    filename VARCHAR(255),
    ocr TEXT,
    pdf VARCHAR(255),
    datahora DATETIME,
    origem VARCHAR(50),
    color_info TEXT,
    adulteracao TINYINT(1),
    INDEX(user_id)
);
