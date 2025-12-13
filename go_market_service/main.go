package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sync"
)

// --- ГЛОБАЛЬНОЕ СОСТОЯНИЕ УЧАСТКОВ ---
// Используем map для хранения участков и Mutex для безопасного доступа
var (
	plotMap = make(map[string]int64) // Ключ: "A1", "B5"; Значение: Telegram user_id
	mapMutex sync.Mutex // Mutex для защиты plotMap от гонки данных
)

// Размер карты: 5x5 (A-E и 1-5)
const (
	MAP_SIZE_X = 5
	MAP_SIZE_Y = 5
)

// Response структуры
type PlotResponse struct {
	Success bool   `json:"success"`
	Message string `json:"message"`
	OwnerID int64  `json:"owner_id,omitempty"` // ID владельца (если есть)
}

type MapState struct {
	Map map[string]int64 `json:"map"`
}

// Проверка и нормализация имени участка (например, "A1")
func isValidPlot(plot string) bool {
	if len(plot) != 2 {
		return false
	}
	// Проверка на латинскую букву (A-E) и цифру (1-5)
	col := plot[0]
	row := plot[1]

	if col < 'A' || col > ('A'+MAP_SIZE_X-1) {
		return false // Колонка невалидна
	}
	if row < '1' || row > ('1'+MAP_SIZE_Y-1) {
		return false // Ряд невалиден
	}
	return true
}

// --- ХЕНДЛЕРЫ API ---

// /claim_plot?plot=A1&user_id=12345
func claimPlotHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	query := r.URL.Query()
	plot := query.Get("plot")
	userIDStr := query.Get("user_id")

	if !isValidPlot(plot) {
		json.NewEncoder(w).Encode(PlotResponse{Success: false, Message: "Неверный формат участка (нужно A1-E5)."})
		return
	}

	userID, err := json.Number(userIDStr).Int64()
	if err != nil || userID == 0 {
		json.NewEncoder(w).Encode(PlotResponse{Success: false, Message: "Неверный user_id."})
		return
	}

	mapMutex.Lock()
	defer mapMutex.Unlock() // Разблокируем при выходе из функции

	if ownerID, exists := plotMap[plot]; exists {
		if ownerID == userID {
			json.NewEncoder(w).Encode(PlotResponse{Success: false, Message: "Участок уже ваш."})
		} else {
			json.NewEncoder(w).Encode(PlotResponse{Success: false, Message: "Участок занят другим игроком.", OwnerID: ownerID})
		}
		return
	}

	// Участок свободен, занимаем его
	plotMap[plot] = userID
	json.NewEncoder(w).Encode(PlotResponse{Success: true, Message: fmt.Sprintf("Участок %s успешно занят!", plot)})
	log.Printf("✅ Plot Claimed: %s by %d", plot, userID)
}

// /get_map
func getMapHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	mapMutex.Lock()
	defer mapMutex.Unlock()

	// Возвращаем копию карты
	mapCopy := make(map[string]int64)
	for k, v := range plotMap {
		mapCopy[k] = v
	}
	json.NewEncoder(w).Encode(MapState{Map: mapCopy})
}

// /check_plot?plot=A1
func checkPlotHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	query := r.URL.Query()
	plot := query.Get("plot")

	if !isValidPlot(plot) {
		json.NewEncoder(w).Encode(PlotResponse{Success: false, Message: "Неверный формат участка."})
		return
	}

	mapMutex.Lock()
	defer mapMutex.Unlock()

	if ownerID, exists := plotMap[plot]; exists {
		json.NewEncoder(w).Encode(PlotResponse{Success: true, Message: "Участок занят.", OwnerID: ownerID})
	} else {
		json.NewEncoder(w).Encode(PlotResponse{Success: true, Message: "Участок свободен."})
	}
}

func main() {
	// Добавляем тестовый участок для примера
	plotMap["C3"] = 99999999 // Административный участок
	
	http.HandleFunc("/claim_plot", claimPlotHandler)
	http.HandleFunc("/get_map", getMapHandler)
	http.HandleFunc("/check_plot", checkPlotHandler)

	fmt.Println("[Go Plot Manager] Starting server on :8081...")
	log.Fatal(http.ListenAndServe(":8081", nil))
}