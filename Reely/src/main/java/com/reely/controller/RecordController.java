package com.reely.controller;
import com.reely.dto.RecordDto;
import com.reely.dto.ResponseDto;
import com.reely.security.SecurityUtil;
import com.reely.service.RecordService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.List;

@RestController
@RequestMapping("/api/record")
public class RecordController {

    private final RecordService recordService;

    public RecordController(RecordService recordService) {
        this.recordService = recordService;
    }

    @GetMapping
    public ResponseEntity<?> getRecordList(@RequestBody RecordDto recordDto) {
        List<RecordDto> recordDtoList = recordService.getRecordList(recordDto);
        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .data(recordDtoList)
                        .build()
        );
    }

    @PostMapping
    public ResponseEntity<?> saveRecord(@RequestBody RecordDto recordDto) {
        Long recordId = recordService.saveRecord(recordDto);
        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .data(recordId)
                        .build()
        );
    }

    @GetMapping("/{recordId}")
    public ResponseEntity<?> getRecord(@PathVariable("recordId") Long recordId,
                                       @RequestBody RecordDto recordDto) {
        recordDto.setRecordId(recordId);
        RecordDto result = recordService.getRecord(recordDto);
        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .data(result)
                        .build()
        );
    }

    @PutMapping("/{recordId}")
    public ResponseEntity<?> updateRecord(@PathVariable Long recordId,
                                          @RequestBody RecordDto recordDto) {

        recordDto.setRecordId(recordId);
        recordService.updateRecord(recordDto);
        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .build()
        );
    }

    @DeleteMapping("/{recordId}")
    public ResponseEntity<?> deleteRecord(@PathVariable Long recordId,
                                          @RequestBody RecordDto recordDto) {
        recordDto.setRecordId(recordId);
        recordService.deleteRecord(recordDto);
        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .build()
        );
    }
}
