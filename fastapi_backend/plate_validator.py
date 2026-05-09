"""
Validador de Placas Brasileiras e Mercosul.
Reduz falsos positivos através de validação de padrão + check-digit.
"""
import re
from typing import Dict, List, Tuple

class PlateValidator:
    """
    Validação de formato de placa brasileira e Mercosul.

    Padrões suportados:
    - Velho: AAAA999 (4 letras + 3 números)
    - Velho: AAA9999 (3 letras + 4 números)
    - Mercosul: AAA9A99 (3 letras + 1 número + 1 letra + 2 números)
    """

    # Padrão velho brasileiro (4 letras 3 números)
    PATTERN_OLD_4L3N = re.compile(r'^[A-Z]{4}[0-9]{3}$')
    # Padrão velho brasileiro (3 letras 4 números)
    PATTERN_OLD_3L4N = re.compile(r'^[A-Z]{3}[0-9]{4}$')
    # Padrão Mercosul (3 letras 1 número 1 letra 2 números)
    PATTERN_MERCOSUL = re.compile(r'^[A-Z]{3}[0-9][A-Z][0-9]{2}$')

    # Letras e números suspeitos (confusão OCR)
    SUSPICIOUS_CHARS = {
        'O': ['0'],  # O vs 0
        '0': ['O'],  # 0 vs O
        'I': ['1', 'L'],  # I vs 1 vs L
        '1': ['I', 'L'],
        'L': ['I', '1'],
        'S': ['5'],  # S vs 5
        '5': ['S'],
        'Z': ['2'],  # Z vs 2
        '2': ['Z'],
    }

    # Estados brasileiros válidos (UF)
    VALID_UFS = {
        'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA',
        'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN',
        'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'
    }

    def __init__(self, strict_mode: bool = False):
        """
        Args:
            strict_mode: Se True, rejeita candidatos com caracteres suspeitos
        """
        self.strict_mode = strict_mode

    def validate(self, plate_text: str) -> Dict:
        """
        Valida placa e retorna score + motivo.

        Returns:
            {
                'valid': bool,
                'score': float (0.0-1.0),
                'pattern': str (old_4l3n, old_3l4n, mercosul, invalid),
                'suspicious_chars': List[Tuple[pos, char, alternatives]],
                'issues': List[str],
                'confidence': float
            }
        """
        plate_clean = plate_text.strip().upper().replace(' ', '')  # Remove espaços internos também
        result = {
            'valid': False,
            'score': 0.0,
            'pattern': 'invalid',
            'suspicious_chars': [],
            'issues': [],
            'confidence': 0.0,
        }

        # Validação básica de comprimento
        if not plate_clean or len(plate_clean) < 7:
            result['issues'].append('Comprimento insuficiente')
            return result

        if len(plate_clean) > 8:
            result['issues'].append('Comprimento excessivo')
            return result

        # Detecção de padrão
        pattern_found = False
        if self.PATTERN_OLD_4L3N.match(plate_clean):
            result['pattern'] = 'old_4l3n'
            pattern_found = True
            score = 0.9
        elif self.PATTERN_OLD_3L4N.match(plate_clean):
            result['pattern'] = 'old_3l4n'
            pattern_found = True
            score = 0.85
        elif self.PATTERN_MERCOSUL.match(plate_clean):
            result['pattern'] = 'mercosul'
            pattern_found = True
            score = 0.95  # Mercosul tem padrão mais rigoroso

        if not pattern_found:
            result['issues'].append('Padrão de placa não reconhecido')
            return result

        # Verificação de caracteres suspeitos
        suspicious = self._find_suspicious_chars(plate_clean)
        result['suspicious_chars'] = suspicious

        if suspicious:
            if self.strict_mode:
                result['issues'].append(f'{len(suspicious)} caracteres suspeitos detectados')
                result['score'] = max(0.0, score - 0.2)
                result['valid'] = False
                return result
            else:
                # Reduz score mas não invalida
                score -= 0.1 * len(suspicious)
                result['issues'].append(f'{len(suspicious)} caracteres potencialmente OCR-confuso')

        # Validação de check-digit para Mercosul (se implementado)
        if result['pattern'] == 'mercosul':
            checksum_valid = self._validate_mercosul_checksum(plate_clean)
            if checksum_valid:
                score += 0.05
            else:
                result['issues'].append('Check-digit Mercosul falhou (pode ser válido)')

        # Resultado final
        result['valid'] = pattern_found and score >= 0.5
        result['score'] = min(1.0, max(0.0, score))
        result['confidence'] = result['score']

        return result

    def _find_suspicious_chars(self, plate: str) -> List[Tuple[int, str, List[str]]]:
        """Identifica caracteres que podem ter sido confundidos no OCR."""
        suspicious = []
        for i, char in enumerate(plate):
            if char in self.SUSPICIOUS_CHARS:
                suspicious.append((i, char, self.SUSPICIOUS_CHARS[char]))
        return suspicious

    def _validate_mercosul_checksum(self, plate: str) -> bool:
        """
        Valida check-digit do padrão Mercosul (dígito final).
        Padrão: AAA9A99 (7 chars)

        Algoritmo simplificado baseado em modulo 9.
        """
        if len(plate) != 7 or plate[3] not in '0123456789':
            return False

        try:
            # Extrai componentes
            letters1 = plate[0:3]  # AAA
            digit1 = int(plate[3])  # 9
            letter2 = plate[4]  # A
            digits_final = int(plate[5:7])  # 99

            # Simula check-digit (implementação simplificada)
            # Nota: O algoritmo real do Mercosul é mais complexo
            # Esta é uma validação básica para detecção de erros grosseiros
            weighted_sum = 0
            weights = [2, 3, 4, 5, 6, 7]
            chars_num = letters1 + str(digit1) + letter2

            for i, ch in enumerate(chars_num):
                if ch.isdigit():
                    weighted_sum += int(ch) * weights[i % len(weights)]
                else:
                    # Letra: usar ord - ord('A') para valor
                    weighted_sum += (ord(ch) - ord('A') + 1) * weights[i % len(weights)]

            check = weighted_sum % 9

            # Comparação com dígito final
            return check == (digits_final % 9)
        except:
            return False

    def suggest_corrections(self, plate_text: str, max_suggestions: int = 3) -> List[str]:
        """
        Sugere correções para placa com caracteres suspeitos.

        Args:
            plate_text: Placa potencialmente errada
            max_suggestions: Número máximo de sugestões

        Returns:
            Lista de placas corrigidas sugeridas
        """
        plate_clean = plate_text.strip().upper()
        validation = self.validate(plate_clean)

        if validation['valid']:
            return [plate_clean]

        if not validation['suspicious_chars']:
            return []

        suggestions = set()
        suggestions.add(plate_clean)

        # Gera variações substituindo caracteres suspeitos
        def generate_variants(text: str, pos_list: List[int]) -> List[str]:
            if not pos_list:
                return [text]

            pos = pos_list[0]
            char = text[pos]
            variants = []

            if char in self.SUSPICIOUS_CHARS:
                for alt in self.SUSPICIOUS_CHARS[char]:
                    new_text = text[:pos] + alt + text[pos+1:]
                    # Recursão para próximo caractere suspeito
                    variants.extend(generate_variants(new_text, pos_list[1:]))
            else:
                variants.extend(generate_variants(text, pos_list[1:]))

            return variants

        suspicious_positions = [pos for pos, _, _ in validation['suspicious_chars']]
        variants = generate_variants(plate_clean, suspicious_positions)

        # Valida variantes e ordena por score
        scored_variants = []
        for variant in variants:
            v_result = self.validate(variant)
            if v_result['valid']:
                scored_variants.append((variant, v_result['score']))

        # Ordena por score descendente
        scored_variants.sort(key=lambda x: x[1], reverse=True)

        result = [variant for variant, _ in scored_variants[:max_suggestions]]
        return result if result else []


def validate_plate(plate_text: str, strict: bool = False) -> Dict:
    """Conveniência: validar uma placa diretamente."""
    validator = PlateValidator(strict_mode=strict)
    return validator.validate(plate_text)


# Exemplos de uso
if __name__ == '__main__':
    validator = PlateValidator(strict_mode=False)

    test_plates = [
        'ABC1234',      # Velho 3L4N - válido
        'ABCD123',      # Velho 4L3N - válido
        'ABC1D23',      # Mercosul - válido
        'AB01D23',      # Mercosul com confusão O-0
        'ABC-1D23',     # Mercosul com hífen (inválido)
        '0BC1234',      # Começa com número (inválido)
        'ABCDEFGH',     # Muito longo
    ]

    for plate in test_plates:
        result = validator.validate(plate)
        print(f"\n{plate}")
        print(f"  Padrão: {result['pattern']}")
        print(f"  Válida: {result['valid']}")
        print(f"  Score: {result['score']:.2f}")
        if result['suspicious_chars']:
            print(f"  Suspeito: {result['suspicious_chars']}")
        if result['issues']:
            print(f"  Problemas: {result['issues']}")

        suggestions = validator.suggest_corrections(plate)
        if suggestions and suggestions[0] != plate:
            print(f"  Sugestões: {suggestions}")
