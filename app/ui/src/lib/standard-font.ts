// Lo que se puede escribir con las fuentes estándar de PDF (Helvetica, Times, Courier), que usan el
// texto libre, las leyendas y los sellos de texto: la codificación WinAnsi (Latin-1 más € — “ ” •…).
// Probado con el motor del visor: un carácter fuera de ella (emojis, ✓, griego, cirílico, chino)
// deja toda la anotación en blanco o desaparece al guardarla. Por eso se quitan antes, con aviso.
//
//   const { text, removed } = standardFontText('Pagado ✅');   // → 'Pagado ', ['✅']

/** Caracteres de WinAnsi fuera de Latin-1 (0x80-0x9F) y su byte. */
export const WIN_ANSI: Record<string, number> = {
  '€': 0x80, '‚': 0x82, 'ƒ': 0x83, '„': 0x84, '…': 0x85, '†': 0x86, '‡': 0x87, 'ˆ': 0x88, '‰': 0x89,
  'Š': 0x8a, '‹': 0x8b, 'Œ': 0x8c, 'Ž': 0x8e, '‘': 0x91, '’': 0x92, '“': 0x93, '”': 0x94, '•': 0x95,
  '–': 0x96, '—': 0x97, '˜': 0x98, '™': 0x99, 'š': 0x9a, '›': 0x9b, 'œ': 0x9c, 'ž': 0x9e, 'Ÿ': 0x9f,
};

/** El byte WinAnsi de `char`, o null si las fuentes estándar no lo tienen. */
export function winAnsiCode(char: string): number | null {
  if (char in WIN_ANSI) return WIN_ANSI[char];
  const code = char.codePointAt(0)!;
  return code >= 0x20 && code <= 0xff && !(code >= 0x7f && code < 0xa0) ? code : null;
}

/** `text` sin lo que las fuentes estándar no pueden dibujar (los saltos de línea se quedan) y lo quitado, sin repetir. */
export function standardFontText(text: string): { text: string; removed: string[] } {
  const removed = new Set<string>();
  let kept = '';
  // Por grafemas: un emoji con tono de piel o una bandera son varios caracteres que se ven como uno.
  for (const { segment } of new Intl.Segmenter('es', { granularity: 'grapheme' }).segment(text.normalize('NFC'))) {
    if (segment === '\n' || segment === '\r\n' || [...segment].every((char) => winAnsiCode(char) !== null)) kept += segment;
    else removed.add(segment);
  }
  return { text: kept, removed: [...removed] };
}
