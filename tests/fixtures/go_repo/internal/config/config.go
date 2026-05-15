// Package config loads server configuration from environment variables.
//
// Uses kelseyhightower/envconfig to map GOAPI_* env vars onto a typed Config
// struct. Validation is performed by the loader and surfaced as a Go error.
package config

import (
	"fmt"
	"time"

	"github.com/kelseyhightower/envconfig"
)

// Config carries every tunable knob for the goapi server.
type Config struct {
	Port              string        `envconfig:"PORT" default:"8080"`
	DatabaseURL       string        `envconfig:"DATABASE_URL" default:"sqlite://./goapi.db"`
	JWTSecret         string        `envconfig:"JWT_SECRET" required:"true"`
	JWTAccessExpires  time.Duration `envconfig:"JWT_ACCESS_EXPIRES" default:"15m"`
	JWTRefreshExpires time.Duration `envconfig:"JWT_REFRESH_EXPIRES" default:"168h"`
	BcryptCost        int           `envconfig:"BCRYPT_COST" default:"12"`
	LogLevel          string        `envconfig:"LOG_LEVEL" default:"info"`
}

// Load reads GOAPI_* variables from the process environment and returns a
// fully-populated, validated Config.
func Load() (*Config, error) {
	var cfg Config
	if err := envconfig.Process("GOAPI", &cfg); err != nil {
		return nil, fmt.Errorf("envconfig: %w", err)
	}
	if err := cfg.validate(); err != nil {
		return nil, err
	}
	return &cfg, nil
}

// validate enforces invariants envconfig cannot express on its own.
func (c *Config) validate() error {
	if len(c.JWTSecret) < 16 {
		return fmt.Errorf("JWT_SECRET must be at least 16 characters")
	}
	if c.BcryptCost < 4 || c.BcryptCost > 20 {
		return fmt.Errorf("BCRYPT_COST must be between 4 and 20, got %d", c.BcryptCost)
	}
	return nil
}

// MustLoad is a convenience wrapper that panics if loading fails. Useful for
// tests and short-lived CLI tools.
func MustLoad() *Config {
	cfg, err := Load()
	if err != nil {
		panic(err)
	}
	return cfg
}
