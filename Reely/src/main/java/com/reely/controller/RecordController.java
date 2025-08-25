package com.reely.controller;
import com.reely.dto.RecordDto;
import com.reely.dto.ResponseDto;
import com.reely.security.SecurityUtil;
import com.reely.service.RecordService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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
    public ResponseEntity<?> getMyRecordList(RecordDto recordDto) {
        List<RecordDto> recordDtoList = recordService.selectRecordList(recordDto);
        return ResponseEntity.ok(
                ResponseDto.builder()
                        .success(true)
                        .data(recordDtoList)
                        .build()
        );
    }
}
