// xcross-compilers: the sort macOS's libc uses, for an iOS gen_snapshot built
// on Linux or Windows.
//
// Dart's GrowableArray::Sort calls the C library's qsort. qsort leaves the
// order of elements that compare equal to the implementation, and Dart sorts
// with ties (stack maps by usage count, dispatch table rows by popularity
// and size), so the same app.dill compiles to a different App on each host
// OS. Flutter's official iOS compiler runs on macOS: with this sort, a
// compiler built elsewhere orders ties as macOS does and writes the same
// bytes.
//
// A C++ transcription of qsort.c and heapsort.c in Apple's Libc
// (stdlib/FreeBSD/, unchanged from Libc-1592 through Libc-1752), which are
// FreeBSD's. Only the swaps are bytewise; which elements move where, and the
// order of every comparison, are the same.

/*-
 * Copyright (c) 1991, 1992, 1993
 *	The Regents of the University of California.  All rights reserved.
 *
 * heapsort.c is derived from software contributed to Berkeley by Ronnie Kon
 * at Mindcraft Inc., Kevin Lew and Elmer Yglesias.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. Neither the name of the University nor the names of its contributors
 *    may be used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE REGENTS AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE REGENTS OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 */

#ifndef RUNTIME_PLATFORM_XCROSS_APPLE_SORT_H_
#define RUNTIME_PLATFORM_XCROSS_APPLE_SORT_H_

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

namespace dart {
namespace xcross {

typedef int (*AppleSortCompare)(const void*, const void*);

inline void AppleSwapBytes(char* a, char* b, size_t n) {
  while (n-- > 0) {
    char t = *a;
    *a++ = *b;
    *b++ = t;
  }
}

inline void AppleCopyBytes(char* to, const char* from, size_t n) {
  while (n-- > 0) *to++ = *from++;
}

// flsl: the 1-based index of the highest set bit, 0 for 0.
inline int AppleFls(uint64_t x) {
  int bit = 0;
  while (x != 0) {
    bit++;
    x >>= 1;
  }
  return bit;
}

// heapsort.c: Knuth vol. 3 p. 145 with the "heapify from the bottom"
// optimization (vol. 3 p. 158 problem 18).
inline void AppleHeapsort(void* vbase, size_t nmemb, size_t size,
                          AppleSortCompare compar) {
  if (nmemb <= 1 || size == 0) return;
  char* k = static_cast<char*>(malloc(size));
  if (k == nullptr) return;
  // Items are numbered from 1 to nmemb.
  char* const base = static_cast<char*>(vbase) - size;
  size_t i, j, l;
  char *p, *t;

  // CREATE(l, nmemb, i, j, t, p, size, ...)
  for (l = nmemb / 2 + 1; --l;) {
    for (i = l; (j = i * 2) <= nmemb; i = j) {
      p = base + j * size;
      if (j < nmemb && compar(p, p + size) < 0) {
        p += size;
        ++j;
      }
      t = base + i * size;
      if (compar(p, t) <= 0) break;
      AppleSwapBytes(t, p, size);
    }
  }

  while (nmemb > 1) {
    AppleCopyBytes(k, base + nmemb * size, size);
    AppleCopyBytes(base + nmemb * size, base + size, size);
    --nmemb;
    // SELECT(i, j, nmemb, t, p, size, k, ...)
    for (i = 1; (j = i * 2) <= nmemb; i = j) {
      p = base + j * size;
      if (j < nmemb && compar(p, p + size) < 0) {
        p += size;
        ++j;
      }
      t = base + i * size;
      AppleCopyBytes(t, p, size);
    }
    for (;;) {
      j = i;
      i = j / 2;
      p = base + j * size;
      t = base + i * size;
      if (j == 1 || compar(k, t) < 0) {
        AppleCopyBytes(p, k, size);
        break;
      }
      AppleCopyBytes(p, t, size);
    }
  }
  free(k);
}

inline char* AppleMed3(char* a, char* b, char* c, AppleSortCompare cmp) {
  return cmp(a, b) < 0 ? (cmp(b, c) < 0 ? b : (cmp(a, c) < 0 ? c : a))
                       : (cmp(b, c) > 0 ? b : (cmp(a, c) < 0 ? a : c));
}

// qsort.c _isort: insertion sort, giving up after swap_limit swaps (0: none).
inline bool AppleInsertionSort(void* a, size_t n, size_t es,
                               AppleSortCompare cmp, int swap_limit) {
  int swap_cnt = 0;
  char* const start = static_cast<char*>(a);
  for (char* pm = start + es; pm < start + n * es; pm += es) {
    for (char* pl = pm; pl > start && cmp(pl - es, pl) > 0; pl -= es) {
      AppleSwapBytes(pl, pl - es, es);
      if (swap_limit && ++swap_cnt > swap_limit) return false;
    }
  }
  return true;
}

// qsort.c _qsort: Bentley & McIlroy's "Engineering a Sort Function", with
// Apple's recursion limit (heapsort) and bounded insertion-sort switch.
inline void AppleQsortImpl(void* a, size_t n, size_t es, AppleSortCompare cmp,
                           int depth_limit) {
  char *pa, *pb, *pc, *pd, *pl, *pm, *pn;
  size_t d1, d2;
  int cmp_result;
  int swap_cnt;

loop:
  swap_cnt = 0;

  if (depth_limit-- <= 0) {
    AppleHeapsort(a, n, es, cmp);
    return;
  }

  if (n <= 7) {
    AppleInsertionSort(a, n, es, cmp, 0);
    return;
  }

  pl = static_cast<char*>(a);
  pm = static_cast<char*>(a) + (n / 2) * es;
  pn = static_cast<char*>(a) + (n - 1) * es;
  if (n > 40) {
    size_t d = (n / 8) * es;
    pl = AppleMed3(pl, pl + d, pl + 2 * d, cmp);
    pm = AppleMed3(pm - d, pm, pm + d, cmp);
    pn = AppleMed3(pn - 2 * d, pn - d, pn, cmp);
  }
  pm = AppleMed3(pl, pm, pn, cmp);

  AppleSwapBytes(static_cast<char*>(a), pm, es);
  pa = pb = static_cast<char*>(a) + es;
  pc = pd = static_cast<char*>(a) + (n - 1) * es;

  for (;;) {
    while (pb <= pc && (cmp_result = cmp(pb, a)) <= 0) {
      if (cmp_result == 0) {
        swap_cnt = 1;
        AppleSwapBytes(pa, pb, es);
        pa += es;
      }
      pb += es;
    }
    while (pb <= pc && (cmp_result = cmp(pc, a)) >= 0) {
      if (cmp_result == 0) {
        swap_cnt = 1;
        AppleSwapBytes(pc, pd, es);
        pd -= es;
      }
      pc -= es;
    }
    if (pb > pc) break;
    AppleSwapBytes(pb, pc, es);
    swap_cnt = 1;
    pb += es;
    pc -= es;
  }

  pn = static_cast<char*>(a) + n * es;
  d1 = static_cast<size_t>(pa - static_cast<char*>(a));
  if (static_cast<size_t>(pb - pa) < d1) d1 = static_cast<size_t>(pb - pa);
  if (d1 > 0) AppleSwapBytes(static_cast<char*>(a), pb - d1, d1);
  d1 = static_cast<size_t>(pd - pc);
  if (static_cast<size_t>(pn - pd) - es < d1) {
    d1 = static_cast<size_t>(pn - pd) - es;
  }
  if (d1 > 0) AppleSwapBytes(pb, pn - d1, d1);

  if (swap_cnt == 0) {  // Switch to insertion sort.
    int r = 1 + static_cast<int>(n / 4);  // n > 7, so r >= 2.
    if (AppleInsertionSort(a, n, es, cmp, r)) return;
  }

  d1 = static_cast<size_t>(pb - pa);
  d2 = static_cast<size_t>(pd - pc);
  if (d1 <= d2) {
    // Recurse on the left partition, then iterate on the right one.
    if (d1 > es) AppleQsortImpl(a, d1 / es, es, cmp, depth_limit);
    if (d2 > es) {
      a = pn - d2;
      n = d2 / es;
      goto loop;
    }
  } else {
    // Recurse on the right partition, then iterate on the left one.
    if (d2 > es) AppleQsortImpl(pn - d2, d2 / es, es, cmp, depth_limit);
    if (d1 > es) {
      n = d1 / es;
      goto loop;
    }
  }
}

// qsort(3) as macOS's libc implements it.
inline void AppleQsort(void* a, size_t n, size_t es, AppleSortCompare cmp) {
  AppleQsortImpl(a, n, es, cmp, 2 * (AppleFls(static_cast<uint64_t>(n)) - 1));
}

}  // namespace xcross
}  // namespace dart

#endif  // RUNTIME_PLATFORM_XCROSS_APPLE_SORT_H_
