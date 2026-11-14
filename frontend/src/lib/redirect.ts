/** Where to go after signing in: a path of this site only. "//host" and "/\host" are read by browsers as another
 * site, so `?next=` could otherwise send the user anywhere (open redirect). */
export function pathOnThisSite(next: string | null): string {
  return next && /^\/(?![/\\])/.test(next) ? next : "/";
}
