package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"

	_ "github.com/mattn/go-sqlite3"
)

// Настройка
const DB_PATH = "./farm_v4.db" // Путь к вашей базе Python-бота!

var (
	db         *sql.DB
	tradeMutex sync.Mutex // Глобальная блокировка для сделок
)

// Структуры для JSON
type BuyRequest struct {
	BuyerID int64 `json:"buyer_id"`
	LotID   int64 `json:"lot_id"`
}

type ListRequest struct {
	SellerID   int64  `json:"seller_id"`
	SellerName string `json:"seller_name"`
	CardID     string `json:"card_id"`
	Price      int64  `json:"price"`
}

type Response struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
}

func main() {
	var err error
	// Подключаемся к той же базе, что и бот
	db, err = sql.Open("sqlite3", DB_PATH)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	// API Маршруты
	http.HandleFunc("/market/buy", buyHandler)
	http.HandleFunc("/market/list", listHandler)

	fmt.Println("🚀 [Go Market Engine] Торговый движок запущен на порту 8082")
	log.Fatal(http.ListenAndServe(":8082", nil))
}

// --- ХЕНДЛЕР ПОКУПКИ (САМОЕ ВАЖНОЕ) ---
func buyHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	
	// Блокируем ВСЕ сделки на долю секунды, чтобы избежать гонки данных
	tradeMutex.Lock()
	defer tradeMutex.Unlock()

	var req BuyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(Response{false, "Неверный запрос"})
		return
	}

	// Начало транзакции (все или ничего)
	tx, err := db.Begin()
	if err != nil {
		json.NewEncoder(w).Encode(Response{false, "Ошибка БД"})
		return
	}
	defer tx.Rollback() // Откат при ошибке

	// 1. Проверяем ЛОТ (существует ли он еще?)
	var sellerID int64
	var price int64
	var cardID string
	
	err = tx.QueryRow("SELECT seller_id, card_id, price FROM market WHERE lot_id = ?", req.LotID).Scan(&sellerID, &cardID, &price)
	if err != nil {
		json.NewEncoder(w).Encode(Response{false, "Лот уже продан или не существует!"})
		return
	}

	if sellerID == req.BuyerID {
		json.NewEncoder(w).Encode(Response{false, "Нельзя купить у самого себя!"})
		return
	}

	// 2. Проверяем БАЛАНС покупателя
	var buyerTomatoes int64
	err = tx.QueryRow("SELECT tomatoes FROM users WHERE user_id = ?", req.BuyerID).Scan(&buyerTomatoes)
	if err != nil {
		json.NewEncoder(w).Encode(Response{false, "Покупатель не найден"})
		return
	}

	if buyerTomatoes < price {
		json.NewEncoder(w).Encode(Response{false, fmt.Sprintf("Не хватает денег! Нужно %d 🍅", price)})
		return
	}

	// 3. ПРОВОДИМ СДЕЛКУ
	
	// Снимаем деньги у покупателя
	_, err = tx.Exec("UPDATE users SET tomatoes = tomatoes - ? WHERE user_id = ?", price, req.BuyerID)
	if err != nil { return }

	// Начисляем деньги продавцу
	_, err = tx.Exec("UPDATE users SET tomatoes = tomatoes + ? WHERE user_id = ?", price, sellerID)
	if err != nil { return }

	// Передаем карту покупателю
	// Проверяем, есть ли она уже у него
	var count int
	err = tx.QueryRow("SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?", req.BuyerID, cardID).Scan(&count)
	if err == sql.ErrNoRows {
		// Нет карты -> INSERT
		_, err = tx.Exec("INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)", req.BuyerID, cardID)
	} else {
		// Есть карта -> UPDATE
		_, err = tx.Exec("UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?", req.BuyerID, cardID)
	}
	if err != nil { return }

	// Удаляем лот с рынка
	_, err = tx.Exec("DELETE FROM market WHERE lot_id = ?", req.LotID)
	if err != nil { return }

	// Фиксируем транзакцию
	err = tx.Commit()
	if err != nil {
		json.NewEncoder(w).Encode(Response{false, "Ошибка фиксации сделки"})
		return
	}

	log.Printf("💰 Сделка! Лот %d продан за %d", req.LotID, price)
	json.NewEncoder(w).Encode(Response{true, "Успешно куплено!"})
}

// --- ХЕНДЛЕР ВЫСТАВЛЕНИЯ ЛОТА ---
func listHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	tradeMutex.Lock()
	defer tradeMutex.Unlock()

	var req ListRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(Response{false, "Bad Request"})
		return
	}

	tx, _ := db.Begin()
	defer tx.Rollback()

	// 1. Проверяем наличие карты у продавца
	var count int
	err := tx.QueryRow("SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?", req.SellerID, req.CardID).Scan(&count)
	if err != nil || count < 1 {
		json.NewEncoder(w).Encode(Response{false, "У вас нет этой карты!"})
		return
	}

	// 2. Забираем карту
	if count == 1 {
		_, err = tx.Exec("DELETE FROM user_cards WHERE user_id = ? AND card_id = ?", req.SellerID, req.CardID)
	} else {
		_, err = tx.Exec("UPDATE user_cards SET count = count - 1 WHERE user_id = ? AND card_id = ?", req.SellerID, req.CardID)
	}
	if err != nil { return }

	// 3. Создаем лот
	_, err = tx.Exec("INSERT INTO market (seller_id, seller_name, card_id, price) VALUES (?, ?, ?, ?)", 
		req.SellerID, req.SellerName, req.CardID, req.Price)
	if err != nil { return }

	tx.Commit()
	json.NewEncoder(w).Encode(Response{true, "Лот создан!"})
}