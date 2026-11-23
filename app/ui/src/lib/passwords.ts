// Contraseñas nuevas para cifrar un PDF: el aviso mientras se escribe. La comprobación que cuenta es
// la de Python al cifrar (pdf_core.security.password_problem, con SASLprep: la norma de PDF para
// AES-256); esta es una aproximación, algo más estricta con los símbolos. No se aplica a las
// contraseñas para abrir un PDF: vale la que tenga.
import { t } from '$texts';

const MAX_BYTES = 127; // AES-256 (revisión 6) usa los primeros 127 bytes en UTF-8
const INVISIBLE = /[\p{Cc}\p{Cf}\p{Co}\p{Cs}\p{Zl}\p{Zp}]/u; // controles, invisibles, uso privado
const SYMBOLS = /[\p{Extended_Pictographic}\p{Cn}\u{10000}-\u{10FFFF}]/u; // emojis, sin asignar y fuera del plano básico

/** Por qué `password` no sirve para cifrar un PDF, o '' si sirve (vacía también sirve: el campo es opcional). */
export function passwordProblem(password: string): string {
  const P = t.common.password.problems;
  if (!password) return '';
  if (INVISIBLE.test(password)) return P.invisible;
  if (SYMBOLS.test(password)) return P.symbols;
  if (password.normalize('NFC') !== password.normalize('NFKC')) return P.normalized;
  if (new TextEncoder().encode(password).length > MAX_BYTES) return P.long(MAX_BYTES);
  return '';
}
