"""
Métricas de qualidade de imagem para placas.
Detecta: blur, rotação, contraste, resolução.
"""
import cv2
import numpy as np
from typing import Dict, Tuple, Optional

class ImageQualityAnalyzer:
    """Análise de qualidade de imagem para otimizar OCR."""

    def __init__(self, target_width: int = 400):
        """
        Args:
            target_width: Largura esperada para placa (usado na escala)
        """
        self.target_width = target_width

    def analyze(self, image_path: str) -> Dict:
        """
        Análise completa de qualidade.

        Returns:
            {
                'blur_score': float (0-1, 0=blurry, 1=sharp),
                'blur_level': str (very_blurry, blurry, acceptable, sharp),
                'rotation_angle': float (graus, -180 a 180),
                'rotation_confidence': float (0-1),
                'contrast_score': float (0-1),
                'brightness_level': str (too_dark, ok, too_bright),
                'resolution_category': str (very_low, low, medium, high),
                'resolution_pixels': int,
                'overall_quality_score': float (0-1),
                'recommendations': List[str],
                'issues': List[str],
            }
        """

        try:
            img = self._load_image_grayscale(image_path)
            if img is None:
                return {
                    'error': 'Falha ao carregar imagem',
                    'image_path': str(image_path),
                    'overall_quality_score': 0.0,
                }

            # Segurança adicional: garante shape 2D antes das métricas.
            if len(img.shape) == 3:
                channels = img.shape[2]
                if channels == 1:
                    img = img[:, :, 0]
                elif channels == 4:
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
                elif channels == 3:
                    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                else:
                    img = np.mean(img, axis=2).astype(np.uint8)
        except Exception as e:
            return {
                'error': f'Erro ao processar: {str(e)}',
                'image_path': str(image_path),
                'overall_quality_score': 0.0
            }

        height, width = img.shape[:2]

        # Análises individuais
        blur_score, blur_level = self._analyze_blur(img)
        rotation_angle, rotation_conf = self._estimate_rotation(img)
        contrast_score = self._analyze_contrast(img)
        brightness_level, brightness_score = self._analyze_brightness(img)
        resolution_category, resolution_pixels = self._categorize_resolution(width, height)

        # Score integrado
        overall_score = self._calculate_overall_score(
            blur_score, contrast_score, brightness_score,
            resolution_category, rotation_conf
        )

        # Recomendações
        recommendations = self._generate_recommendations(
            blur_score, contrast_score, brightness_level,
            resolution_category, rotation_angle
        )

        issues = self._identify_issues(
            blur_level, contrast_score, brightness_level,
            resolution_category, rotation_angle
        )

        return {
            'blur_score': float(blur_score),
            'blur_level': blur_level,
            'rotation_angle': float(rotation_angle),
            'rotation_confidence': float(rotation_conf),
            'contrast_score': float(contrast_score),
            'brightness_level': brightness_level,
            'brightness_score': float(brightness_score),
            'resolution_category': resolution_category,
            'resolution_pixels': int(resolution_pixels),
            'resolution_dimensions': f'{width}x{height}',
            'overall_quality_score': float(overall_score),
            'recommendations': recommendations,
            'issues': issues,
        }

    def _load_image_grayscale(self, image_path: str) -> Optional[np.ndarray]:
        """Carrega imagem de forma robusta para paths Unicode no Windows."""
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            return img

        try:
            data = np.fromfile(image_path, dtype=np.uint8)
            if data.size == 0:
                return None

            decoded = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
            if decoded is None:
                return None

            if len(decoded.shape) == 3:
                channels = decoded.shape[2]
                if channels == 1:
                    return decoded[:, :, 0]
                if channels == 4:
                    return cv2.cvtColor(decoded, cv2.COLOR_BGRA2GRAY)
                return cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)

            return decoded
        except Exception:
            return None

    def _analyze_blur(self, img: np.ndarray) -> Tuple[float, str]:
        """
        Detecta blur usando variância do Laplaciano.
        Scores altos = nitidez, baixos = blur.
        """
        laplacian_var = cv2.Laplacian(img, cv2.CV_64F).var()

        # Normalização para 0-1
        # Referência: imagens nítidas típicas têm variância > 100
        blur_score = min(1.0, laplacian_var / 500.0)

        if blur_score < 0.2:
            blur_level = 'very_blurry'
        elif blur_score < 0.4:
            blur_level = 'blurry'
        elif blur_score < 0.7:
            blur_level = 'acceptable'
        else:
            blur_level = 'sharp'

        return blur_score, blur_level

    def _estimate_rotation(self, img: np.ndarray) -> Tuple[float, float]:
        """
        Estima ângulo de rotação usando Hough line detection.
        Retorna: (ângulo em graus, confiança 0-1)
        """
        try:
            # Detector de bordas
            edges = cv2.Canny(img, 50, 150)

            # Hough line detection
            lines = cv2.HoughLines(edges, 1, np.pi / 180, 50)

            if lines is None or len(lines) < 5:
                return 0.0, 0.0

            # Extrai ângulos das linhas
            angles = []
            for line in lines[:20]:  # Top 20 linhas
                rho, theta = line[0]
                angle = np.degrees(theta) - 90  # Converti para graus, alinha horizontal
                angles.append(angle)

            # Histograma de ângulos
            angle_hist, _ = np.histogram(angles, bins=36, range=(-90, 90))
            max_bin = np.argmax(angle_hist)
            dominant_angle = -90 + max_bin * 5  # Aproximação

            # Normaliza para -180 a 180
            if dominant_angle > 90:
                dominant_angle -= 180
            elif dominant_angle < -90:
                dominant_angle += 180

            # Confiança baseada na prevalência do ângulo dominante
            confidence = max(angle_hist) / len(angles) if angles else 0.0

            return dominant_angle, confidence
        except:
            return 0.0, 0.0

    def _analyze_contrast(self, img: np.ndarray) -> float:
        """Calcula score de contraste (RMS contrast)."""
        # RMS (Root Mean Square) contrast
        img_float = img.astype(np.float32) / 255.0
        contrast = img_float.std()

        # Normaliza: tipicamente 0.0-0.5, normalizamos para 0-1
        contrast_score = min(1.0, contrast * 2.0)

        return contrast_score

    def _analyze_brightness(self, img: np.ndarray) -> Tuple[str, float]:
        """Analisa nível de brilho."""
        brightness = np.mean(img)

        # Normaliza para 0-1
        brightness_score = brightness / 255.0

        if brightness < 50:
            level = 'too_dark'
        elif brightness < 100:
            level = 'dark'
        elif brightness > 200:
            level = 'too_bright'
        elif brightness > 180:
            level = 'bright'
        else:
            level = 'ok'

        # Score: melhor em torno de 100-180 (cinza médio)
        if 100 <= brightness <= 180:
            brightness_adj_score = 1.0
        elif 50 <= brightness < 100 or 180 < brightness <= 220:
            brightness_adj_score = 0.8
        elif 30 <= brightness < 50 or 220 < brightness <= 240:
            brightness_adj_score = 0.5
        else:
            brightness_adj_score = 0.2

        return level, brightness_adj_score

    def _categorize_resolution(self, width: int, height: int) -> Tuple[str, int]:
        """Categoriza resolução efetiva."""
        pixels = width * height

        if pixels < 20000:  # < 141x141
            category = 'very_low'
        elif pixels < 100000:  # < 316x316
            category = 'low'
        elif pixels < 500000:  # < 707x707
            category = 'medium'
        else:
            category = 'high'

        return category, pixels

    def _calculate_overall_score(
        self,
        blur_score: float,
        contrast_score: float,
        brightness_score: float,
        resolution_category: str,
        rotation_confidence: float
    ) -> float:
        """Calcula score integrado (ponderado)."""
        # Pesos
        weights = {
            'blur': 0.35,
            'contrast': 0.25,
            'brightness': 0.15,
            'resolution': 0.15,
            'rotation': 0.10,
        }

        # Score de resolução
        resolution_scores = {
            'very_low': 0.3,
            'low': 0.6,
            'medium': 0.85,
            'high': 1.0,
        }
        resolution_score = resolution_scores.get(resolution_category, 0.5)

        # Score de rotação (menor é melhor)
        rotation_score = 1.0 - min(1.0, rotation_confidence * 0.5)

        # Cálculo ponderado
        overall = (
            blur_score * weights['blur'] +
            contrast_score * weights['contrast'] +
            brightness_score * weights['brightness'] +
            resolution_score * weights['resolution'] +
            rotation_score * weights['rotation']
        )

        return overall

    def _generate_recommendations(
        self,
        blur_score: float,
        contrast_score: float,
        brightness_level: str,
        resolution_category: str,
        rotation_angle: float
    ) -> list:
        """Gera recomendações de melhoria."""
        recommendations = []

        if blur_score < 0.4:
            recommendations.append('Imagem muito desfocada. Considere super-resolução ou re-captura.')

        if blur_score < 0.7:
            recommendations.append('Aplicar deconvolução ou super-resolução pode melhorar OCR.')

        if contrast_score < 0.3:
            recommendations.append('Contraste baixo. Aplicar equalização adaptativa (CLAHE).')

        if brightness_level in ['too_dark', 'too_bright']:
            recommendations.append(f'Brilho inadequado ({brightness_level}). Ajustar luminosidade.')

        if resolution_category == 'very_low':
            recommendations.append('Resolução muito baixa (<200px). Super-resolução recomendada.')
        elif resolution_category == 'low':
            recommendations.append('Resolução baixa. Upscaling ou re-captura em melhor qualidade.')

        if abs(rotation_angle) > 15:
            recommendations.append(f'Imagem rotacionada {rotation_angle:.1f}°. Realizar rotação corretiva.')

        return recommendations

    def _identify_issues(
        self,
        blur_level: str,
        contrast_score: float,
        brightness_level: str,
        resolution_category: str,
        rotation_angle: float
    ) -> list:
        """Identifica problemas críticos."""
        issues = []

        if blur_level == 'very_blurry':
            issues.append('CRÍTICO: Imagem muito desfocada')

        if contrast_score < 0.2:
            issues.append('CRÍTICO: Contraste insuficiente')

        if brightness_level in ['too_dark', 'too_bright']:
            issues.append(f'AVISO: Brilho inadequado')

        if resolution_category == 'very_low':
            issues.append('AVISO: Resolução muito baixa')

        if abs(rotation_angle) > 30:
            issues.append(f'AVISO: Rotação excessiva ({rotation_angle:.1f}°)')

        return issues


def analyze_image_quality(image_path: str) -> Dict:
    """Conveniência: analisar qualidade de imagem."""
    analyzer = ImageQualityAnalyzer()
    return analyzer.analyze(image_path)


# Exemplos
if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        result = analyze_image_quality(image_path)

        print(f"\n=== Análise de Qualidade ===")
        print(f"Blur: {result['blur_level']} ({result['blur_score']:.2f})")
        print(f"Rotação: {result['rotation_angle']:.1f}° (conf: {result['rotation_confidence']:.2f})")
        print(f"Contraste: {result['contrast_score']:.2f}")
        print(f"Brilho: {result['brightness_level']}")
        print(f"Resolução: {result['resolution_category']} ({result['resolution_dimensions']})")
        print(f"\nScore Geral: {result['overall_quality_score']:.2f}/1.0")

        if result['issues']:
            print(f"\nProblemas: {result['issues']}")

        if result['recommendations']:
            print(f"\nRecomendações: {result['recommendations']}")
    else:
        print("Uso: python quality_metrics.py <caminho_imagem>")
