// Package middleware — request/response logging.
package middleware

import (
	"log"
	"net/http"
	"time"
)

// statusRecorder wraps http.ResponseWriter to remember the status code we
// ended up writing so the logger can include it.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

// WriteHeader captures the status code on its way out.
func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

// RequestLogger is chi middleware that logs method, path, status, and
// duration for every request that flows through it.
func RequestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		log.Printf(
			"%s %s -> %d (%s)",
			r.Method,
			r.URL.Path,
			rec.status,
			time.Since(start),
		)
	})
}
