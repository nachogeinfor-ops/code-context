// Package main is the entry point for the goapi HTTP server.
//
// Wires config -> database -> repository -> service -> handler layers and
// starts a chi-based HTTP server listening on the configured port.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"github.com/example/goapi/internal/config"
	"github.com/example/goapi/internal/database"
	"github.com/example/goapi/internal/handlers"
	appmw "github.com/example/goapi/internal/middleware"
	"github.com/example/goapi/internal/repository"
	"github.com/example/goapi/internal/services"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("config: %v", err)
	}

	db, err := database.Open(cfg)
	if err != nil {
		log.Fatalf("database: %v", err)
	}
	defer db.Close()

	userRepo := repository.NewUserRepository(db)
	itemRepo := repository.NewItemRepository(db)

	authSvc := services.NewAuthService(cfg)
	userSvc := services.NewUserService(userRepo, authSvc)
	itemSvc := services.NewItemService(itemRepo)

	authH := handlers.NewAuthHandler(userSvc, authSvc)
	usersH := handlers.NewUsersHandler(userSvc)
	itemsH := handlers.NewItemsHandler(itemSvc)

	r := chi.NewRouter()
	r.Use(middleware.Recoverer)
	r.Use(appmw.RequestLogger)

	r.Post("/auth/login", authH.Login)
	r.Post("/auth/refresh", authH.Refresh)

	r.Group(func(r chi.Router) {
		r.Use(appmw.RequireAuth(authSvc))
		r.Route("/users", func(r chi.Router) {
			r.Post("/", usersH.CreateUser)
			r.Get("/", usersH.ListUsers)
			r.Get("/{id}", usersH.GetUser)
			r.Patch("/{id}", usersH.UpdateUser)
			r.Delete("/{id}", usersH.DeleteUser)
		})
		r.Route("/items", func(r chi.Router) {
			r.Post("/", itemsH.CreateItem)
			r.Get("/", itemsH.ListItems)
			r.Get("/{id}", itemsH.GetItem)
			r.Patch("/{id}", itemsH.UpdateItem)
			r.Delete("/{id}", itemsH.DeleteItem)
		})
	})

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           r,
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Printf("listening on :%s", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("server: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	<-stop

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Printf("shutdown: %v", err)
	}
}
